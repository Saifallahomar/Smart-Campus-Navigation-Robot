"""
The Robot orchestrator — the main loop that ties everything together.

Conversation flow
-----------------
1. Wait in idle (camera preview live) until a face is detected.
2. Greet the person and enter a session.
3. Inside the session: listen → transcribe → answer → speak → listen again.
4. Brief face-detection flickers do NOT end the session — the session ends
   only after the face has been absent for ``person_lost_timeout`` seconds
   (default 8 s, configurable in config.json).
5. After the session ends, return to idle and wait for the next person.

Wave detection (optional, enabled in config)
--------------------------------------------
When enabled, the robot watches for a hand wave ABOVE the detected face and
shows a notice on screen. Set `wave_detection.enabled = true` in config.json.

Camera preview runs continuously via the CameraFeed background thread, so
the user always sees themselves on screen regardless of the robot's state.
All hardware is cleaned up on exit, even on crash or Ctrl+C.
"""

import atexit
import json
import os
import signal
import subprocess
import time

from config.settings import settings
from src.ai.assistant import Assistant
from src.ai.knowledge import Knowledge
from src.ai.question_logger import QuestionLogger
from src.ai.language import (
    UNSUPPORTED_REPLY,
    detect_language,
    fallback_phrase,
    is_supported_input,
)
from src.audio.player import Player
from src.audio.recorder import Recorder
from src.audio.wakeword import WakeWord
from src.core.states import RobotState
from src.hardware.head_controller import build_head_controller
from src.ui.face import Face
from src.utils.logging_setup import get_logger
from src.hardware.arduino import ArduinoController
from src.core.phone_server import PhoneControlServer
from src.ui.video_player import VideoPlayer
from src.vision.camera import Camera, CameraFeed
from src.vision.tracker import FaceTracker
from src.vision.wave import WaveDetector

log = get_logger("robot")

STOP_WORDS = ["stop", "exit", "توقف", "arrêt"]

GOODBYE_WORDS = [
    "bye", "goodbye", "see you", "see ya", "farewell",
    "that's all", "that is all", "i'm done", "i am done",
    "مع السلامة", "وداعا",
    "au revoir", "à bientôt", "bonne journée",
]

GREETING_WORDS = [
    "hello", "hi", "hey", "مرحبا", "السلام", "أهلا",
    "salut", "bonjour", "bonsoir",
]

# --- Voice commands for the physical head servo (English + a little AR/FR) ----
# Centre is checked first so "look forward" never matches left/right.
# Phrases are kept specific (they mention the head or "look") so normal
# navigation questions like "where do I turn left?" don't move the servo.
HEAD_CENTER_PHRASES = [
    "look forward", "look ahead", "look straight", "look in front",
    "look center", "look centre", "head center", "head centre",
    "move your head center", "move your head centre",
    "center your head", "centre your head", "head forward",
    "انظر أمامك", "حرك رأسك للأمام", "regarde devant", "tête au centre",
]
HEAD_LEFT_PHRASES = [
    "look left", "head left", "look to your left", "look to the left",
    "move your head left", "turn your head left",
    "انظر يسار", "حرك رأسك يسار", "regarde à gauche", "tourne la tête à gauche",
    "tête à gauche",
]
HEAD_RIGHT_PHRASES = [
    "look right", "head right", "look to your right", "look to the right",
    "move your head right", "turn your head right",
    "انظر يمين", "حرك رأسك يمين", "regarde à droite", "tourne la tête à droite",
    "tête à droite",
]

# Short spoken acknowledgements for head moves, per language.
HEAD_ACKS = {
    "left":   {"english": "Okay, looking left.",
               "arabic":  "حسنًا، أنظر إلى اليسار.",
               "french":  "D'accord, je regarde à gauche."},
    "right":  {"english": "Okay, looking right.",
               "arabic":  "حسنًا، أنظر إلى اليمين.",
               "french":  "D'accord, je regarde à droite."},
    "center": {"english": "Okay, looking forward.",
               "arabic":  "حسنًا، أنظر إلى الأمام.",
               "french":  "D'accord, je regarde devant."},
}

# --- "What can you see?" one-shot camera vision -------------------------------
#
# Phrases are checked as substrings of the lowercased question.  A match means
# the robot captures ONE frame and sends it to OpenAI vision.  No live video.
#
# Adding a phrase here is the only change needed to support a new trigger.
VISION_QUERY_PHRASES = [
    # ── general sight queries ──────────────────────────────────────────────
    "what can you see", "what do you see", "what are you seeing",
    "describe what you can see", "describe what you see", "describe the scene",
    "what's in front of you", "what is in front of you",
    "what's in front of me",  "what is in front of me",
    "what can you see right now", "what do you see right now",
    "what are you looking at", "can you see anything",
    # ── can/do you see me ─────────────────────────────────────────────────
    "can you see me", "do you see me", "can you see us",
    "are you looking at me", "do you see anyone",
    "am i in front of you", "am i visible to you",
    "is anyone in front of you", "is there anyone in front of you",
    # ── object identification ("this" implies something physically present) ─
    "what is this", "what's this",
    "what am i holding",
    "can you identify this", "identify this",
    "describe this",
    # ── colour / appearance ────────────────────────────────────────────────
    "what colour is this", "what color is this",
    "what colour is that", "what color is that",
    # ── engineering / electronics part identification ──────────────────────
    "what type of sensor", "what type of motor",
    "what type of component", "what type of part",
    "what type of device", "what type of board",
    # ── yes/no object check: "is this a …" / "is this an …" ──────────────
    "is this a", "is this an",
    # ── Arabic ────────────────────────────────────────────────────────────
    "ماذا ترى", "ماذا تشاهد", "صف ما تراه", "هل تراني",
    "ما هذا", "ما لون هذا", "ما نوع هذا",
    "هل يمكنك التعرف على هذا",
    # ── French ────────────────────────────────────────────────────────────
    "que vois-tu", "que voyez-vous", "qu'est-ce que tu vois",
    "décris ce que tu vois", "est-ce que tu me vois",
    "qu'est-ce que c'est", "quelle couleur",
    "quel type de capteur", "quel type de moteur",
    # ── Chinese (Mandarin) ────────────────────────────────────────────────
    "你能看到什么", "你看到了什么", "这是什么", "描述你看到的",
    "这是什么颜色", "这是什么类型",
]
CAMERA_UNAVAILABLE = {
    "english": "Sorry, my camera isn't available right now.",
    "arabic":  "عذرًا، الكاميرا غير متاحة الآن.",
    "french":  "Désolé, ma caméra n'est pas disponible pour le moment.",
    "chinese": "抱歉，我的摄像头现在不可用。",
}
VISION_FAILED = {
    "english": "Sorry, I couldn't make out what I'm seeing right now.",
    "arabic":  "عذرًا، لم أتمكن من تمييز ما أراه الآن.",
    "french":  "Désolé, je n'arrive pas à distinguer ce que je vois.",
    "chinese": "抱歉，我现在看不清楚。",
}

# --- Arduino voice commands --------------------------------------------------
#
# These are checked BEFORE the AI, exactly like the head-servo commands.
# If any phrase matches the user's question, the robot performs the action
# directly without calling OpenAI.

ARM_RUN_PHRASES = [
    # English — giving / fetching
    "give me", "hand me", "pass me", "get me", "fetch me",
    "can i have", "can you give", "can you get",
    "start the arm", "run the arm", "use the arm", "activate the arm",
    "start arm", "run arm",
    # Common demo item
    "chocolate", "give me chocolate",
    # Arabic
    "أعطني", "ناولني", "أحضر لي",
    # French
    "donne-moi", "passe-moi", "apporte-moi",
]

ARM_HOME_PHRASES = [
    "arm home", "home the arm", "retract the arm", "put the arm away",
    "home arm", "reset arm",
]

MOVE_FORWARD_PHRASES = [
    "move forward", "go forward", "drive forward", "move ahead", "go ahead",
    "تحرك للأمام", "avance", "avancer",
]

MOVE_BACKWARD_PHRASES = [
    "move backward", "go backward", "reverse", "move back", "go back",
    "back up",
    "تحرك للخلف", "recule", "reculer",
]

TOUR_PHRASES = [
    "start the tour", "begin the tour", "give me a tour",
    "take me on a tour", "show me around", "start tour",
    "campus tour", "give a tour",
]

# Words/phrases that signal the user is asking for directions.
# At least one must appear for a navigation video to be shown.
# This prevents e.g. "what time does the library close?" from triggering a video.
_NAV_INTENT_PHRASES = [
    # English — direct questions
    "where is", "where's", "where can i find",
    "how do i get", "how to get", "how do i reach",
    "how do i find", "how to find",
    # English — action requests
    "show me", "show me the way", "take me to",
    "navigate to", "walk to", "lead me to",
    # English — softer phrases
    "directions to", "route to", "way to",
    "get to the", "find the",
    "can you show me", "can you take me", "can you direct me",
    "i need to get to", "i want to go to", "i'm looking for",
    "looking for the", "need directions",
    # Arabic
    "أين", "كيف أصل", "كيف أذهب", "دلني على",
    # French
    "où est", "comment aller", "montrez-moi", "comment je peux aller",
]

# What the robot says when it runs the arm.
ARM_REPLY = {
    "english": "Here you go.",
    "arabic":  "تفضل.",
    "french":  "Voilà pour vous.",
    "chinese": "给您。",
}

# What the robot says when the obstacle is detected.
OBSTACLE_MSG = "Please clear the way so I can continue safely."

# How long to hold the ERROR face before returning to idle.
ERROR_HOLD_SECS = 2.0

# Minimum seconds between verbal greetings.
# Prevents the robot from saying "Hi there!" again when the face-detection
# flickers or the person steps back briefly and then returns.
GREETING_COOLDOWN_SECS = 25.0

# Max number of extra recording attempts when no audio is captured (mic hiccup).
_MAX_LISTEN_RETRIES = 2


class Robot:
    def __init__(self):
        self.settings   = settings
        self.running    = True
        self._do_shutdown  = False
        self._cleaned_up   = False
        self._last_face_time = 0.0   # tracks when a face was last seen in a session
        self._last_greet_time = 0.0  # tracks when the robot last spoke a verbal greeting

        self.voice_path  = str(settings.project_root / "voice.wav")
        self.answer_path = str(settings.project_root / "answer.wav")

        # Core components
        self.face      = Face(settings)
        self.camera    = Camera(settings)
        self.feed      = CameraFeed(self.camera,
                                    fps=int(settings.vision.get("feed_fps", 15)))
        self.recorder  = Recorder(settings)
        self.player    = Player(settings)
        self.assistant = Assistant(settings)
        self.knowledge = Knowledge(settings)
        self.wakeword  = WakeWord(settings)
        self.tracker   = FaceTracker()
        self.head      = build_head_controller(settings)

        # Wave detection (lightweight, disabled by default)
        wave_cfg = settings.get('wave_detection') or {}
        self.wave_detector = WaveDetector(
            enabled=bool(wave_cfg.get('enabled', False)),
            motion_threshold=float(wave_cfg.get('motion_threshold', 30)),
            min_motion_frames=int(wave_cfg.get('min_motion_frames', 8)),
            cooldown=float(wave_cfg.get('cooldown_seconds', 3.0)),
        )

        # Arduino motor controller (falls back to mock if not connected).
        self.arduino = ArduinoController(settings)
        self.arduino.on_obstacle = self._on_obstacle
        # Flag set by the Arduino reader thread when an obstacle is reported.
        # The main loop reads it and speaks the message safely from its thread.
        self._obstacle_pending = False

        # Phone motor control web server — shares the same arduino and camera.
        # Started in run() after the camera feed is live.
        phone_cfg = settings.get("phone_server") or {}
        self._phone_server_enabled = bool(phone_cfg.get("enabled", True))
        self.phone_server = PhoneControlServer(
            arduino=self.arduino,
            camera_feed=self.feed,
            port=int(phone_cfg.get("port", 5000)),
        )

        # Navigation video player — shows route videos in the preview area.
        self.video_player  = VideoPlayer(settings.project_root)
        self._nav_videos   = self._load_nav_videos()

        self.q_logger    = QuestionLogger(settings)
        self.messages    = self.knowledge.build_messages()
        self.state       = RobotState.IDLE
        # track_face now drives the SCREEN EYES only (the physical servo moves
        # only on a voice command — see _parse_head_command / _handle_head_command).
        self.track_face  = bool(settings.vision.get("track_face", True))
        # When nobody is seen for this long, ease the eyes back to centre.
        self._face_gone_since = None
        servo_cfg = settings.get("servo") or {}
        self._recenter_delay = float(servo_cfg.get("recenter_delay_seconds", 1.5))
        # How far "look left"/"look right" turn, as a fraction of full travel.
        look_deg = float(servo_cfg.get("voice_look_angle_deg", 60))
        max_deg = float(servo_cfg.get("max_angle", 90)) or 90.0
        self._voice_look_frac = max(0.0, min(1.0, look_deg / max_deg))

        # How long a person can be absent before the session ends (default 8 s).
        conv_cfg = settings.get('conversation') or {}
        self._lost_timeout = float(conv_cfg.get('person_lost_timeout', 8.0))

        atexit.register(self.cleanup)
        for sig in ("SIGINT", "SIGTERM"):
            if hasattr(signal, sig):
                try:
                    signal.signal(getattr(signal, sig), self._on_signal)
                except (ValueError, OSError):
                    pass

    # ============================================================= main loop

    def run(self):
        log.info("Robot starting. Mock mode: %s", self.settings.mock_mode)

        self.camera.start()
        self.feed.start()      # background thread keeps camera preview live

        # Start phone control web server — runs in background, shares arduino + camera.
        if self._phone_server_enabled:
            self.phone_server.start()

        # One-time, friendly checks so problems are visible instead of silent.
        self._startup_checks()
        self._render(RobotState.IDLE)

        try:
            while self.running:
                if not self._wait_for_face():
                    break
                self._run_session()

        except KeyboardInterrupt:
            log.info("Interrupted by keyboard.")
        finally:
            self.cleanup()
            self._maybe_power_off()

    # ====================================================== startup checks

    def _startup_checks(self):
        """
        Friendly, one-time checks at boot. Nothing here stops the robot — the
        face always runs — but problems are logged clearly and shown on screen
        so they are easy to spot instead of failing silently.
        """
        # Microphone
        if not getattr(self.recorder, "available", False) and not self.settings.mock_mode:
            log.warning("Microphone not available — check devices.mic_device in config.json.")

        # Speaker
        if not self.settings.mock_mode and not self.player.aplay_available():
            log.warning("Speaker tool 'aplay' missing — install alsa-utils for sound.")

        # AI / internet. If it's not ready the robot stays open and recovers
        # automatically once the key/internet is sorted, so just notify.
        if not self.assistant.ready:
            log.warning("AI is not ready — check OPENAI_API_KEY in .env and the internet.")
            self._show_startup_notice(
                "Starting up... waiting for the internet / AI connection.")

    def _show_startup_notice(self, message, seconds=4.0):
        """
        Show a brief friendly notice on the ERROR face, then carry on. The badge
        shows the ERROR status ("Connection problem"); the caption shows the
        detail message. The robot keeps running and recovers on its own once the
        connection is back.
        """
        self.face.set_caption(robot=message)
        self._hold(RobotState.ERROR, seconds)
        self.face.clear_caption()

    # ========================================================= session loop

    def _run_session(self):
        """
        Active conversation session, entered after a face is detected.

        Keeps listening and answering while the person is present.
        If no face is seen for longer than ``person_lost_timeout`` seconds
        (default 8 s), the session ends and the robot returns to idle so it
        can greet the next person.  Brief face-detection flickers do NOT end
        the session early — only a sustained absence does.
        """
        log.info("Session started.")
        self._last_face_time = time.time()

        while self.running:
            # Keep face timestamp fresh.
            if self.feed.has_face:
                self._last_face_time = time.time()

            # End session only after the full grace period has elapsed.
            absent = time.time() - self._last_face_time
            if absent > self._lost_timeout:
                log.info("Person absent %.1fs — returning to idle.", absent)
                break

            # --- Obstacle message (set by Arduino reader thread) ---------------
            if self._obstacle_pending:
                self._obstacle_pending = False
                log.info("Speaking obstacle message.")
                self.face.set_caption(robot=OBSTACLE_MSG)
                self._speak(OBSTACLE_MSG)
                self.face.clear_caption()
                self._render(RobotState.IDLE)
                continue

            # --- Movement pause ------------------------------------------------
            # While the robot body is physically moving (but NOT during a tour),
            # keep the camera live but skip voice listening until Arduino sends DONE.
            if self.arduino.is_moving and not self.arduino.is_touring:
                self.face.set_status("Robot is moving...")
                self._render(RobotState.IDLE)
                time.sleep(0.1)
                continue

            # Wake word gate (no-op when disabled, returns True immediately).
            if not self.wakeword.wait_for_wake(on_tick=self._session_idle_tick):
                continue

            # Record and transcribe.
            question = self._listen_and_transcribe()
            if question is None:
                self._render(RobotState.IDLE)
                continue

            # Hard stop word → shut down everything.
            if self._is_stop(question):
                log.info("Stop word heard — shutting down.")
                self.running = False
                break

            # Friendly goodbye → say bye and end this session.
            if self._is_goodbye(question):
                log.info("User said goodbye.")
                self._farewell()
                break

            # --- Arduino voice commands (handled locally, no AI needed) --------

            # Tour request → ask for spoken password.
            if self._is_tour_command(question):
                log.info("Tour command heard.")
                self._handle_tour_request()
                continue

            # Arm run → give the item.
            if self._is_arm_run(question):
                log.info("Arm run command.")
                self._handle_arm_run(question)
                continue

            # Arm home → retract.
            if self._is_arm_home(question):
                log.info("Arm home command.")
                self.arduino.home_arm()
                self._render(RobotState.IDLE)
                continue

            # Move forward.
            if self._is_move_forward(question):
                log.info("Move forward command.")
                self._handle_move("forward", question)
                continue

            # Move backward.
            if self._is_move_backward(question):
                log.info("Move backward command.")
                self._handle_move("backward", question)
                continue

            # --- Voice command to move the physical head servo (no AI call) ----
            head_dir = self._parse_head_command(question)
            if head_dir:
                log.info("Head command: %s", head_dir)
                self._handle_head_command(head_dir, question)
                continue

            # "What can you see?" → capture ONE frame and describe it.
            if self._is_vision_query(question):
                log.info("Vision query.")
                self._handle_vision_query(question)
                continue

            # Unsupported language / garbled STT output.
            if not is_supported_input(question):
                log.info("Unsupported language — asking to repeat.")
                self.face.set_caption(robot=UNSUPPORTED_REPLY)
                self._speak(UNSUPPORTED_REPLY)
                self.face.clear_caption()
                self._hold(RobotState.CONFUSED, 0.5)
                self._render(RobotState.IDLE)
                continue

            # Normal Q&A turn.
            log.info("Thinking...")
            answer, is_fallback = self._get_answer(question)
            self.q_logger.record(detect_language(question), question, answer,
                                 unsure=is_fallback)
            log.info("Speaking: %s", answer[:80])
            self.face.set_caption(robot=answer)

            # Check for a navigation video BEFORE speaking so we can start
            # both the audio and the video at the same time.
            nav_video = self._find_nav_video(question)
            if nav_video:
                self._speak_with_nav_video(answer, nav_video)
            else:
                self._speak(answer)
                self._post_expression(question, is_fallback)

            self.face.clear_caption()
            self._render(RobotState.IDLE)

        log.info("Session ended — returning to idle.")
        self._render(RobotState.IDLE)

    # ========================================================== face waiting

    def _wait_for_face(self):
        """Idle (with live camera preview) until a person is seen."""
        if not self.feed.available:
            self._hold(RobotState.IDLE, 0.5)
            return self.running

        log.info("Waiting for a person... (camera feed active)")
        self.wave_detector.reset()

        while self.running:
            self._refresh_preview()
            self._render(RobotState.IDLE)

            if self.feed.has_face:
                # _refresh_preview() above already drives head tracking.
                log.info("Person detected — starting session.")
                self._greet_on_face_detect()
                return True
        return False

    def _greet_on_face_detect(self):
        """
        Brief greeting when someone first appears.

        If wave detection is enabled, watch for a wave for up to 1.5 seconds
        and show a notice on the screen. Either way the robot always speaks a
        short hello so the person knows it's ready to listen.
        """
        if self.wave_detector.enabled:
            deadline = time.time() + 1.5
            while self.running and time.time() < deadline and self.feed.has_face:
                self._refresh_preview()
                self._render(RobotState.FACE_DETECTED)
                if self.feed.frame is not None:
                    if self.wave_detector.update(self.feed.frame, self.feed.faces):
                        log.info("Wave detected — showing notice.")
                        self.face.set_notice("👋 User is waving", 2.5)
                        break
        else:
            self._hold(RobotState.FACE_DETECTED, 0.4)

        # Only greet verbally if enough time has passed since the last greeting.
        # This prevents the robot from saying "Hi there!" repeatedly when face
        # detection flickers or the person steps back for a moment.
        since = time.time() - self._last_greet_time
        if since >= GREETING_COOLDOWN_SECS:
            self._proactive_greet()
        else:
            log.info("Greeting cooldown active (%.0fs since last) — skipping verbal greeting.", since)

    # ========================================================= helpers

    def _proactive_greet(self):
        """Friendly verbal greeting when a new person is detected."""
        self._last_greet_time = time.time()
        msg = "Hi there! How can I help you today?"
        self.face.set_caption(robot=msg)
        self._speak(msg)
        self.face.clear_caption()

    def _farewell(self):
        """Friendly goodbye before returning to idle."""
        conv = self.settings.get('conversation') or {}
        msg = conv.get('farewell_message', "Bye! Have a great day!")
        self.face.set_caption(robot=msg)
        self._speak(msg)
        self.face.clear_caption()
        self._hold(RobotState.HAPPY, 0.8)
        self._render(RobotState.IDLE)

    # ================================================== Arduino handlers

    def _on_obstacle(self):
        """Called by the Arduino reader thread when an obstacle is detected."""
        self._obstacle_pending = True   # main thread will speak it safely

    def _handle_tour_request(self):
        """Ask for a spoken password; if correct, send TOUR to the Arduino."""
        prompt = "Please say the tour password to start."
        self.face.set_caption(robot=prompt)
        self._speak(prompt)
        self.face.clear_caption()

        password = self._listen_and_transcribe()
        if password is None:
            return

        if password.strip().lower() == self.arduino.tour_password.strip().lower():
            msg = "Starting the campus tour! Please follow me."
            self.face.set_caption(robot=msg)
            self._speak(msg)
            self.face.clear_caption()
            self.arduino.start_tour()
            log.info("Tour started.")
        else:
            msg = "Sorry, that password is incorrect."
            self.face.set_caption(robot=msg)
            self._speak(msg)
            self.face.clear_caption()
            self._render(RobotState.IDLE)

    def _handle_arm_run(self, question):
        """Send ARM_RUN to the Arduino and say 'Here you go.'"""
        self.arduino.run_arm()
        lang = detect_language(question)
        msg  = ARM_REPLY.get(lang, ARM_REPLY["english"])
        self.face.set_caption(robot=msg)
        self._speak(msg)
        self.face.clear_caption()
        self._render(RobotState.IDLE)

    def _handle_move(self, direction, question):
        """Send a movement command and announce it."""
        if direction == "forward":
            self.arduino.move_forward()
            msg = "Moving forward."
        else:
            self.arduino.move_backward()
            msg = "Moving backward."
        self.face.set_caption(robot=msg)
        self._speak(msg)
        self.face.clear_caption()
        self._render(RobotState.IDLE)

    # ================================================== Arduino phrase checks

    @staticmethod
    def _is_arm_run(text):
        t = text.lower()
        return any(p in t for p in ARM_RUN_PHRASES)

    @staticmethod
    def _is_arm_home(text):
        t = text.lower()
        return any(p in t for p in ARM_HOME_PHRASES)

    @staticmethod
    def _is_move_forward(text):
        t = text.lower()
        return any(p in t for p in MOVE_FORWARD_PHRASES)

    @staticmethod
    def _is_move_backward(text):
        t = text.lower()
        return any(p in t for p in MOVE_BACKWARD_PHRASES)

    @staticmethod
    def _is_tour_command(text):
        t = text.lower()
        return any(p in t for p in TOUR_PHRASES)

    # =========================================================== helpers

    def _session_idle_tick(self):
        """
        Tick called while waiting for a wake word (or between turns when wake
        word is disabled). Keeps the camera preview and face alive, and updates
        the face-seen timestamp so the session timeout stays accurate.
        """
        if self.feed.has_face:
            self._last_face_time = time.time()
        self._render(RobotState.IDLE)
        return not self.running  # True = stop waiting

    def _listen_and_transcribe(self):
        """
        Record the user, transcribe, and return text — or None.

        Retries up to _MAX_LISTEN_RETRIES times when the recorder returns
        nothing but the person is still present (transient mic failure or
        pre-speech timeout in recorder).
        Returns None immediately when the person is gone or the robot stops.
        """
        self.face.clear_caption()

        for attempt in range(1 + _MAX_LISTEN_RETRIES):
            if attempt == 0:
                log.info("Listening started...")
            else:
                log.info("No speech detected — retrying (%d/%d)...",
                         attempt, _MAX_LISTEN_RETRIES)
                # Brief on-screen hint so the person knows the robot is still ready.
                self.face.set_caption(robot="I'm listening — please speak clearly.")
                self._hold(RobotState.LISTENING, 0.8)
                self.face.clear_caption()

            audio_file = self.recorder.record_until_silence(
                self.voice_path, on_tick=self._listen_tick)

            if audio_file is None:
                if not self.running:
                    return None
                # No speech in this attempt — retry if we have attempts left.
                if attempt < _MAX_LISTEN_RETRIES:
                    continue
                log.info("No speech after all retries — returning to idle.")
                return None

            log.info("Speech captured — transcribing...")
            self._render(RobotState.THINKING)
            question = self.assistant.transcribe(audio_file)

            if not question:
                log.info("Empty or failed transcript — asking the user to repeat.")
                self._hold(RobotState.CONFUSED, 0.6)
                line = fallback_phrase("didnt_catch", "english")
                self.face.set_caption(robot=line)
                self._speak(line)
                self.face.clear_caption()
                return None

            log.info("You said: %s", question)
            self.face.set_caption(user=question)
            return question

        log.info("No speech after all retries — returning to idle.")
        return None

    def _get_answer(self, question):
        """Return (answer_text, is_fallback). Never raises."""
        # Fast local FAQ (off by default).
        faq = self.knowledge.match_faq(question)
        if faq is not None:
            return faq, False

        # Ask the AI.
        self._render(RobotState.THINKING)
        self.messages.append({"role": "user", "content": question})
        self._trim_history()

        answer = self.assistant.chat(self.messages)

        if answer is None:
            # Network / API failure — drop unanswered turn to keep history clean.
            self.messages.pop()
            log.warning("AI connection failed — internet may be down.")
            self.face.set_caption(robot="Internet connection lost. Reconnecting...")
            self._hold(RobotState.ERROR, 3.0)
            self.face.clear_caption()
            return ("Sorry, I can't reach my connection right now. "
                    "Please try again in a moment!"), True

        self.messages.append({"role": "assistant", "content": answer})
        log.info("Robot: %s", answer)
        return answer, self.assistant.is_fallback(answer)

    def _speak(self, text):
        """Generate and play TTS audio while animating the mouth."""
        self._render(RobotState.SPEAKING)

        audio_out = self.assistant.synthesize(text, self.answer_path)

        if audio_out is None or not os.path.exists(audio_out) \
                or os.path.getsize(audio_out) < 200:
            log.warning("No TTS audio — showing caption only.")
            self._hold(RobotState.SPEAKING, min(6.0, max(2.0, len(text) / 15.0)))
            return

        proc = self.player.play_async(self.answer_path)
        if proc is None:
            self._hold(RobotState.SPEAKING, min(6.0, max(2.0, len(text) / 15.0)))
            return

        while self.player.is_playing() and self.running:
            if self.feed.has_face:
                self._last_face_time = time.time()
            self._refresh_preview()
            self._pump()
            self.face.render(RobotState.SPEAKING)

        if not self.running:
            self.player.stop()
            return

        # Brief pause after audio ends: lets speaker echo die out so it is not
        # picked up as the start of the next recording.
        self._hold(RobotState.SPEAKING, 0.35)

    def _post_expression(self, question, is_fallback):
        if is_fallback:
            self._hold(RobotState.CONFUSED, 0.8)
        elif self._is_greeting(question):
            self._hold(RobotState.HAPPY, 0.9)

    # ============================================================ tiny helpers

    def _refresh_preview(self):
        """Push the latest camera frame to the face UI — called everywhere."""
        if self.feed.available:
            self.face.set_preview(
                self.feed.frame,
                faces=self.feed.faces,
                frame_size=(self.camera.width, self.camera.height))

            # Screen EYE gaze follows the person (smoothly). The physical head
            # servo does NOT auto-follow — it only moves on a voice command.
            if self.track_face:
                if self.feed.has_face:
                    offset = self.tracker.update(
                        self.feed.faces, self.camera.width, self.camera.height)
                    if offset:
                        # Negate x: camera and display both face the user, so
                        # left/right from camera's perspective is mirrored on screen.
                        self.face.set_gaze(-offset[0], offset[1])
                    self._face_gone_since = None
                else:
                    # Brief grace period (detection flickers), then look ahead.
                    now = time.time()
                    if self._face_gone_since is None:
                        self._face_gone_since = now
                    elif now - self._face_gone_since > self._recenter_delay:
                        self.tracker.reset()
                        self.face.set_gaze(0.0, 0.0)

            # Wave detection → show a clear "User is waving" banner on screen.
            if (self.wave_detector.enabled and self.feed.has_face
                    and self.feed.frame is not None):
                if self.wave_detector.update(self.feed.frame, self.feed.faces):
                    log.info("Wave detected — showing notice.")
                    self.face.set_notice("👋 User is waving", 2.5)

    def _listen_tick(self, volume, started):
        """Called every audio chunk to keep the UI alive during recording."""
        if self.feed.has_face:
            self._last_face_time = time.time()
        self._refresh_preview()
        self.face.set_status(RobotState.LISTENING.status_text)
        self.face.render(RobotState.LISTENING)
        self._pump()
        if not self.running:
            return True
        return False

    def _render(self, state):
        self.state = state
        self.face.set_status(state.status_text)
        self._refresh_preview()
        self.face.render(state)
        self._pump()

    def _hold(self, state, seconds):
        """Show a state for ``seconds`` while keeping the UI responsive."""
        self.state = state
        self.face.set_status(state.status_text)
        end = time.time() + seconds
        while time.time() < end and self.running:
            if self.feed.has_face:
                self._last_face_time = time.time()
            self._refresh_preview()
            self.face.render(state)
            self._pump()

    def _pump(self):
        for event in self.face.pump_events():
            if event == "quit":
                log.info("Quit requested.")
                self.running = False
            elif event == "shutdown":
                log.info("Safe shutdown requested.")
                self.running = False
                self._do_shutdown = True
            elif event == "tour_requested":
                log.info("Tour button pressed.")
                self._handle_tour_request()
        return self.running

    def _trim_history(self):
        max_turns = int(self.settings.ai.get("max_history_turns", 12))
        limit = 1 + max_turns * 2
        if len(self.messages) > limit:
            self.messages = [self.messages[0]] + self.messages[-(max_turns * 2):]

    @staticmethod
    def _is_stop(text):
        t = text.lower()
        return any(w in t for w in STOP_WORDS)

    @staticmethod
    def _is_goodbye(text):
        t = text.lower()
        return any(w in t for w in GOODBYE_WORDS)

    @staticmethod
    def _is_greeting(text):
        t = text.lower()
        return any(w in t for w in GREETING_WORDS)

    # ----------------------------------------------------- head voice commands

    @staticmethod
    def _parse_head_command(text):
        """Return 'left' / 'right' / 'center' / None for a head-move command."""
        t = text.lower()
        if any(p in t for p in HEAD_CENTER_PHRASES):
            return "center"
        if any(p in t for p in HEAD_LEFT_PHRASES):
            return "left"
        if any(p in t for p in HEAD_RIGHT_PHRASES):
            return "right"
        return None

    def _handle_head_command(self, direction, question):
        """Move the physical servo to a safe preset and say a short ack."""
        frac = self._voice_look_frac
        target = {"left": -frac, "right": frac, "center": 0.0}[direction]
        self.head.look(target)   # negative = robot's left; flip with servo.invert

        lang = detect_language(question)
        ack = HEAD_ACKS[direction].get(lang, HEAD_ACKS[direction]["english"])
        self.face.set_caption(robot=ack)
        self._speak(ack)
        self.face.clear_caption()
        self._render(RobotState.IDLE)

    # ------------------------------------------------------ camera vision query

    @staticmethod
    def _is_vision_query(text):
        t = text.lower()
        return any(p in t for p in VISION_QUERY_PHRASES)

    def _handle_vision_query(self, question):
        """Capture ONE current frame and speak a short description of it."""
        lang = detect_language(question)

        if not self.feed.available or self.feed.frame is None:
            msg = CAMERA_UNAVAILABLE.get(lang, CAMERA_UNAVAILABLE["english"])
            self.face.set_caption(robot=msg)
            self._speak(msg)
            self.face.clear_caption()
            self._render(RobotState.IDLE)
            return

        self._render(RobotState.THINKING)
        frame = self.feed.frame          # single snapshot — no live streaming
        description = self.assistant.describe_scene(frame, language=lang,
                                                    question=question)

        if not description:
            description = VISION_FAILED.get(lang, VISION_FAILED["english"])

        self.face.set_caption(robot=description)
        self._speak(description)
        self.face.clear_caption()
        self._render(RobotState.IDLE)

    # ====================================================== navigation videos

    def _load_nav_videos(self) -> list:
        """Load navigation video routes from data/video_map.json."""
        path = self.settings.data_dir / "video_map.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            routes = data.get("routes", [])
            log.info("Loaded %d navigation video route(s).", len(routes))
            return routes
        except FileNotFoundError:
            log.info("video_map.json not found — navigation videos disabled.")
            return []
        except Exception as exc:
            log.warning("Could not load video_map.json: %s", exc)
            return []

    def _find_nav_video(self, question: str):
        """
        Return the video path if this is a directions query for a known
        destination, otherwise return None.

        Two conditions must both be true:
          1. A direction-intent phrase is present (e.g. "where is", "show me").
          2. A destination keyword from video_map.json appears as a whole word.

        This prevents "what time does the library close?" from triggering a
        video even though it names a place.
        """
        if not self._nav_videos:
            return None

        q = question.lower()
        has_intent = any(phrase in q for phrase in _NAV_INTENT_PHRASES)
        if not has_intent:
            return None

        # Pad with spaces so whole-word matching works for short keywords like
        # "su" — avoids false matches inside words like "issue" or "visual".
        q_padded = " " + q.strip() + " "
        for route in self._nav_videos:
            keywords  = route.get("keywords", [])
            label     = route.get("label", "?")
            video_rel = route.get("video", "")
            if any((" " + kw.strip() + " ") in q_padded for kw in keywords):
                log.info("Navigation video matched: %s", label)
                return video_rel

        return None

    def _speak_with_nav_video(self, text: str, video_rel_path: str):
        """
        Synthesise TTS, then play the route video full-screen while the audio
        runs simultaneously in the background.

        Flow:
          1. Synthesise TTS (network call, must finish before playback starts).
          2. Start aplay subprocess (non-blocking — audio begins immediately).
          3. Play video full-screen via VideoPlayer; _nav_video_tick renders
             each frame and keeps pygame events alive.
          4. After video ends, wait for audio to finish if still playing.
          5. Brief post-speech pause so the mic echo doesn't start a new turn.

        If the video file is missing, voice-only playback continues normally.
        """
        self._render(RobotState.SPEAKING)
        audio_out = self.assistant.synthesize(text, self.answer_path)

        # Start audio playback — non-blocking subprocess.
        proc = self.player.play_async(audio_out) if audio_out else None

        # Play video full-screen concurrently with the audio subprocess.
        log.info("Showing navigation video: %s", video_rel_path)
        self.face.set_status("Showing route...")
        played = self.video_player.play(
            video_rel_path,
            face=self.face,
            on_frame_tick=self._nav_video_tick,
        )

        if not played:
            log.info("Navigation video unavailable — voice only.")
            if proc is None:
                # No audio either; hold the speaking face for a sensible time.
                self._hold(RobotState.SPEAKING,
                           min(8.0, max(2.0, len(text) / 15.0)))

        # Video ended — wait for audio if it's still running.
        while self.player.is_playing() and self.running:
            if self.feed.has_face:
                self._last_face_time = time.time()
            self._refresh_preview()
            self._pump()
            self.face.render(RobotState.IDLE)

        # Brief pause so speaker echo doesn't bleed into the next recording.
        self._hold(RobotState.IDLE, 0.35)

    def _nav_video_tick(self) -> bool:
        """
        Called by VideoPlayer after each frame is pushed into face via set_preview.

        Renders the frame full-screen (replacing the normal face + camera layout),
        processes pygame events, and refreshes the face-presence timer.

        Returns True to stop the video (shutdown button pressed or robot stopping).
        """
        if self.feed.has_face:
            self._last_face_time = time.time()
        self.face.render_fullscreen_frame()
        self._pump()
        return not self.running   # True = stop video

    # =========================================================== shutdown

    def _on_signal(self, signum, frame):
        log.info("Received signal %s — stopping.", signum)
        self.running = False

    def _maybe_power_off(self):
        if self._do_shutdown and self.settings.ui.get("shutdown_action") == "poweroff":
            log.info("Powering off the Raspberry Pi...")
            try:
                subprocess.run(["sudo", "shutdown", "-h", "now"], check=False)
            except Exception as exc:
                log.error("Power off failed: %s", exc)

    def cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        log.info("Cleaning up...")
        for component, name in [
            (self.arduino,  "arduino"),
            (self.player,   "player"),
            (self.feed,     "camera feed"),
            (self.camera,   "camera"),
            (self.wakeword, "wakeword"),
            (self.head,     "head"),
            (self.face,     "face"),
        ]:
            try:
                component.stop() if hasattr(component, "stop") else component.close()
            except Exception as exc:
                log.debug("Cleanup error (%s): %s", name, exc)
        log.info("Robot stopped.")
