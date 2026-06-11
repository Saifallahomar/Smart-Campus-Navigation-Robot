"""
The Robot orchestrator — the main loop that ties everything together.

Conversation flow
-----------------
1. Wait for a face (idle with live camera preview).
2. Start a session — the robot stays in conversation mode as long as
   the person is visible.
3. Within the session: wake word → listen → transcribe → answer → speak.
   Repeat indefinitely until the person leaves or says goodbye.
4. If the person disappears for longer than `conversation.person_lost_timeout`
   seconds, the session ends and the robot returns to idle.

Wave detection (optional, off by default)
-----------------------------------------
When enabled, the robot watches for a hand wave ABOVE the detected face while
in idle/waiting mode and greets the person proactively before they speak.
Set `wave_detection.enabled = true` in config.json to try it.

Camera preview runs continuously via the CameraFeed background thread, so
the user always sees themselves on screen regardless of the robot's state.
All hardware is cleaned up on exit, even on crash or Ctrl+C.
"""

import atexit
import os
import signal
import subprocess
import time

from config.settings import settings
from src.ai.assistant import Assistant
from src.ai.knowledge import Knowledge
from src.ai.language import (
    UNSUPPORTED_REPLY,
    fallback_phrase,
    is_supported_input,
)
from src.audio.player import Player
from src.audio.recorder import Recorder
from src.audio.wakeword import WakeWord
from src.core.states import RobotState
from src.hardware.head_controller import HeadController
from src.ui.face import Face
from src.utils.logging_setup import get_logger
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

# How long to hold the ERROR face before returning to idle.
ERROR_HOLD_SECS = 2.0


class Robot:
    def __init__(self):
        self.settings   = settings
        self.running    = True
        self._do_shutdown  = False
        self._cleaned_up   = False
        self._last_face_time = 0.0   # tracks when a face was last seen in a session

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
        self.head      = HeadController(settings)

        # Wave detection (lightweight, disabled by default)
        wave_cfg = settings.get('wave_detection') or {}
        self.wave_detector = WaveDetector(
            enabled=bool(wave_cfg.get('enabled', False)),
            motion_threshold=float(wave_cfg.get('motion_threshold', 30)),
            min_motion_frames=int(wave_cfg.get('min_motion_frames', 8)),
            cooldown=float(wave_cfg.get('cooldown_seconds', 3.0)),
        )

        self.messages    = self.knowledge.build_messages()
        self.state       = RobotState.IDLE
        self.track_face  = bool(settings.vision.get("track_face", True))

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

        # One-time, friendly checks so problems are visible instead of silent.
        self._startup_checks()
        self._render(RobotState.IDLE)

        try:
            while self.running:
                # Phase 1: idle until someone appears.
                if not self._wait_for_face():
                    break
                # Phase 2: multi-turn conversation session.
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
        Multi-turn conversation while the person stays visible.

        The session ends when:
          - The person has been absent for `person_lost_timeout` seconds.
          - The person says a goodbye word.
          - A stop word triggers full shutdown.
          - The optional `max_session_seconds` limit is reached.
        """
        log.info("Session started.")
        self._last_face_time = time.time()
        session_start = time.time()

        conv = self.settings.get('conversation') or {}
        lost_timeout = float(conv.get('person_lost_timeout', 8.0))
        max_secs = conv.get('max_session_seconds')
        max_secs = float(max_secs) if max_secs else None

        while self.running:
            # Keep the face timestamp fresh while person is visible.
            if self.feed.has_face:
                self._last_face_time = time.time()

            # End session if person has been gone too long.
            absent = time.time() - self._last_face_time
            if absent > lost_timeout:
                log.info("Person absent %.1fs — ending session.", absent)
                break

            # Optional hard session time limit.
            if max_secs and (time.time() - session_start) > max_secs:
                log.info("Session time limit (%.0fs) reached.", max_secs)
                self._farewell()
                break

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

            # Friendly goodbye → end session only.
            if self._is_goodbye(question):
                log.info("User said goodbye.")
                self._farewell()
                break

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
            answer, is_fallback = self._get_answer(question)
            self.face.set_caption(robot=answer)
            self._speak(answer)
            self._post_expression(question, is_fallback)
            self.face.clear_caption()
            self._render(RobotState.IDLE)

        log.info("Session ended.")
        self._render(RobotState.IDLE)

    # ========================================================== face waiting

    def _wait_for_face(self):
        """Idle (with live camera preview) until a person is seen."""
        if not self.feed.available:
            self._hold(RobotState.IDLE, 0.5)
            return self.running

        log.info("Waiting for a person...")
        self.wave_detector.reset()

        while self.running:
            self._refresh_preview()
            self._render(RobotState.IDLE)

            if self.feed.has_face:
                if self.track_face:
                    offset = self.tracker.update(
                        self.feed.faces, self.camera.width, self.camera.height)
                    if offset:
                        self.head.aim(*offset)
                log.info("Face detected.")
                self._greet_on_face_detect()
                return True
        return False

    def _greet_on_face_detect(self):
        """
        Brief greeting when someone first appears.

        If wave detection is enabled, watch for a wave for up to 2 seconds
        and greet proactively. Otherwise show the standard face-detected
        animation for 0.6 s.
        """
        if self.wave_detector.enabled:
            deadline = time.time() + 2.0
            while self.running and time.time() < deadline and self.feed.has_face:
                self._refresh_preview()
                self._render(RobotState.FACE_DETECTED)
                if self.feed.frame is not None:
                    if self.wave_detector.update(self.feed.frame, self.feed.faces):
                        log.info("Wave detected — greeting proactively.")
                        self._proactive_greet()
                        return
        else:
            self._hold(RobotState.FACE_DETECTED, 0.6)

    # ========================================================= helpers

    def _proactive_greet(self):
        """Friendly greeting triggered by a detected wave."""
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
        """Record the user, transcribe, and return text — or None on failure."""
        self.face.clear_caption()
        log.info("Listening...")

        audio_file = self.recorder.record_until_silence(
            self.voice_path, on_tick=self._listen_tick)
        if audio_file is None:
            return None

        self._render(RobotState.THINKING)
        log.info("Transcribing...")
        question = self.assistant.transcribe(audio_file)

        if not question:
            # Unclear speech or failed transcription — say a friendly line in
            # English (we have no reliable text to detect a language from) and
            # invite the person to try again, instead of silently moving on.
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
            self._hold(RobotState.ERROR, ERROR_HOLD_SECS)
            return ("Sorry, I seem to have lost my connection. "
                    "Could you try again in a moment?"), True

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
            self._refresh_preview()
            self._pump()
            self.face.render(RobotState.SPEAKING)

        if not self.running:
            self.player.stop()

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

    def _listen_tick(self, volume, started):
        """Called every audio chunk to keep the UI alive during recording."""
        self._refresh_preview()
        self.face.set_status(RobotState.LISTENING.status_text)
        self.face.render(RobotState.LISTENING)
        self._pump()
        return not self.running   # True stops the recording

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
            (self.player,   "player"),
            (self.feed,     "camera feed"),
            (self.camera,   "camera"),
            (self.wakeword, "wakeword"),
            (self.face,     "face"),
        ]:
            try:
                component.stop() if hasattr(component, "stop") else component.close()
            except Exception as exc:
                log.debug("Cleanup error (%s): %s", name, exc)
        log.info("Robot stopped.")
