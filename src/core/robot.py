"""
The Robot orchestrator - the main loop that ties everything together.

Flow (same idea as the original voice_ai.py, now safe and modular):
    wait for a face  ->  (optional wake word)  ->  listen  ->  transcribe
    ->  answer (FAQ or AI)  ->  speak with mouth movement  ->  back to idle

The face shows the matching emotion at each step and captions what was said.
All hardware is cleaned up on exit, even on crash or Ctrl+C.
"""

import atexit
import signal
import subprocess
import time

from config.settings import settings
from src.ai.assistant import Assistant
from src.ai.knowledge import Knowledge
from src.audio.player import Player
from src.audio.recorder import Recorder
from src.audio.wakeword import WakeWord
from src.core.states import RobotState
from src.hardware.head_controller import HeadController
from src.ui.face import Face
from src.utils.logging_setup import get_logger
from src.vision.camera import Camera
from src.vision.tracker import FaceTracker

log = get_logger("robot")

STOP_WORDS = ["stop", "exit", "توقف"]
GREETING_WORDS = ["hello", "hi", "hey", "مرحبا", "السلام", "salut", "bonjour", "hola"]


class Robot:
    def __init__(self):
        self.settings = settings
        self.running = True
        self._do_shutdown = False
        self._cleaned_up = False

        # Working audio files (kept in the project folder).
        self.voice_path = str(settings.project_root / "voice.wav")
        self.answer_path = str(settings.project_root / "answer.wav")

        # Build all the parts.
        self.face = Face(settings)
        self.camera = Camera(settings)
        self.recorder = Recorder(settings)
        self.player = Player(settings)
        self.assistant = Assistant(settings)
        self.knowledge = Knowledge(settings)
        self.wakeword = WakeWord(settings)
        self.tracker = FaceTracker()
        self.head = HeadController(settings)

        self.messages = self.knowledge.build_messages()
        self.state = RobotState.IDLE

        self.show_preview = bool(settings.vision.get("show_preview", True))
        self.track_face = bool(settings.vision.get("track_face", True))

        # Make sure we always clean up.
        atexit.register(self.cleanup)
        for sig in ("SIGINT", "SIGTERM"):
            if hasattr(signal, sig):
                try:
                    signal.signal(getattr(signal, sig), self._on_signal)
                except (ValueError, OSError):
                    pass  # not in main thread / not supported

    # ------------------------------------------------------------- main loop
    def run(self):
        log.info("Robot starting. Mock mode: %s", self.settings.mock_mode)
        if not self.assistant.ready:
            log.warning("AI is not ready - check your OPENAI_API_KEY in .env. "
                        "The face will still run.")
        self.camera.start()
        self._render(RobotState.IDLE)

        try:
            while self.running:
                if not self._wait_for_face():
                    break

                if not self.wakeword.wait_for_wake(on_tick=lambda: not self.running):
                    continue

                question = self._listen_and_transcribe()
                if question is None:
                    continue
                if self._is_stop(question):
                    log.info("Stop word heard - shutting down conversation.")
                    break

                answer, is_fallback = self._get_answer(question)
                self.face.set_caption(robot=answer)

                self._speak(answer)
                self._post_expression(question, is_fallback)
                self.face.clear_caption()
                self._render(RobotState.IDLE)
        except KeyboardInterrupt:
            log.info("Interrupted by keyboard.")
        finally:
            self.cleanup()
            self._maybe_power_off()

    # --------------------------------------------------------- loop helpers
    def _wait_for_face(self):
        """Idle until a person is seen. Returns False if the user quit."""
        # Without a camera (mock/dev) just proceed so the loop is testable.
        if not self.camera.available:
            self._hold(RobotState.IDLE, 0.5)
            return self.running

        log.info("Waiting for a person...")
        w = self.camera.width
        h = self.camera.height
        last_check = 0.0
        check_interval = 0.2  # run face detection ~5x/sec (cheaper than every frame)

        while self.running:
            self._pump()

            # Render the idle face every frame for smooth blinking...
            self._render(RobotState.IDLE)

            # ...but only run the (heavier) camera capture + detection periodically.
            now = time.time()
            if now - last_check < check_interval:
                continue
            last_check = now

            frame = self.camera.capture_frame()
            faces = self.camera.detect_faces(frame) if frame is not None else []

            if self.show_preview and frame is not None:
                self.face.set_preview(frame)
            if self.track_face and faces:
                offset = self.tracker.update(faces, w, h)
                if offset:
                    self.head.aim(*offset)

            if faces:
                log.info("Face detected.")
                self._hold(RobotState.FACE_DETECTED, 0.5)
                return True
        return False

    def _listen_and_transcribe(self):
        """Record the user and return the transcribed text, or None."""
        self.face.clear_caption()
        self.state = RobotState.LISTENING
        log.info("Listening...")

        audio_file = self.recorder.record_until_silence(
            self.voice_path, on_tick=self._listen_tick)
        if audio_file is None:
            return None

        self._render(RobotState.THINKING)
        log.info("Understanding...")
        question = self.assistant.transcribe(audio_file)

        if not question:
            log.info("Empty/failed transcript - skipping.")
            self._hold(RobotState.CONFUSED, 1.0)
            return None

        log.info("You said: %s", question)
        self.face.set_caption(user=question)
        return question

    def _get_answer(self, question):
        """Return (answer_text, is_fallback)."""
        # 1) Try the fast local FAQ (off by default).
        faq = self.knowledge.match_faq(question)
        if faq is not None:
            return faq, False

        # 2) Ask the AI.
        self._render(RobotState.THINKING)
        self.messages.append({"role": "user", "content": question})
        self._trim_history()
        answer = self.assistant.chat(self.messages)

        if answer is None:
            # Drop the unanswered user turn so history stays clean.
            self.messages.pop()
            return ("Sorry, I'm having trouble connecting right now. "
                    "Please try again in a moment."), True

        self.messages.append({"role": "assistant", "content": answer})
        log.info("Robot: %s", answer)
        return answer, self.assistant.is_fallback(answer)

    def _speak(self, text):
        """Play the TTS answer while animating the mouth."""
        self.state = RobotState.SPEAKING
        self.face.set_status(RobotState.SPEAKING.status_text)

        audio_out = self.assistant.synthesize(text, self.answer_path)

        if audio_out is None:
            # No audio - show the answer on screen for a readable moment.
            self._hold(RobotState.SPEAKING, min(6.0, max(2.0, len(text) / 15.0)))
            return

        proc = self.player.play_async(self.answer_path)
        if proc is None:
            self._hold(RobotState.SPEAKING, min(6.0, max(2.0, len(text) / 15.0)))
            return

        while self.player.is_playing() and self.running:
            self._pump()
            mouth_open = int(time.time() * 6) % 2 == 0
            self.face.render(RobotState.SPEAKING, mouth_open=mouth_open)
        if not self.running:
            self.player.stop()

    def _post_expression(self, question, is_fallback):
        if is_fallback:
            self._hold(RobotState.CONFUSED, 0.8)
        elif self._is_greeting(question):
            self._hold(RobotState.HAPPY, 0.9)

    # --------------------------------------------------------- tiny helpers
    def _listen_tick(self, volume, started):
        """Called every audio chunk; keep the UI alive, allow quitting."""
        self.face.set_status(RobotState.LISTENING.status_text)
        self.face.render(RobotState.LISTENING)
        self._pump()
        return not self.running  # True => stop recording

    def _render(self, state):
        self.state = state
        self.face.set_status(state.status_text)
        self.face.render(state)
        self._pump()

    def _hold(self, state, seconds):
        """Show a state for a while, keeping the UI responsive."""
        self.state = state
        self.face.set_status(state.status_text)
        end = time.time() + seconds
        while time.time() < end and self.running:
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
        limit = 1 + max_turns * 2  # system message + N user/assistant pairs
        if len(self.messages) > limit:
            self.messages = [self.messages[0]] + self.messages[-(max_turns * 2):]

    @staticmethod
    def _is_stop(text):
        t = text.lower()
        return any(w in t for w in STOP_WORDS)

    @staticmethod
    def _is_greeting(text):
        t = text.lower()
        return any(w in t for w in GREETING_WORDS)

    # ------------------------------------------------------------- shutdown
    def _on_signal(self, signum, frame):
        log.info("Received signal %s - stopping.", signum)
        self.running = False

    def _maybe_power_off(self):
        action = self.settings.ui.get("shutdown_action", "quit")
        if self._do_shutdown and action == "poweroff":
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
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self.camera.stop()
        except Exception:
            pass
        try:
            self.wakeword.close()
        except Exception:
            pass
        try:
            self.face.close()
        except Exception:
            pass
        log.info("Robot stopped.")
