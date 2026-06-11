"""
The Robot orchestrator — the main loop that ties everything together.

Flow:
    wait for a face  →  (optional wake word)  →  listen  →  transcribe
    →  answer (FAQ or AI)  →  speak with mouth movement  →  back to idle

Camera preview runs continuously (via CameraFeed background thread) so the
user always sees themselves on screen regardless of the robot's current state.
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
from src.ai.language import UNSUPPORTED_REPLY, is_supported_input
from src.audio.player import Player
from src.audio.recorder import Recorder
from src.audio.wakeword import WakeWord
from src.core.states import RobotState
from src.hardware.head_controller import HeadController
from src.ui.face import Face
from src.utils.logging_setup import get_logger
from src.vision.camera import Camera, CameraFeed
from src.vision.tracker import FaceTracker

log = get_logger("robot")

STOP_WORDS     = ["stop", "exit", "توقف", "arrêt"]
GREETING_WORDS = ["hello", "hi", "hey", "مرحبا", "السلام", "أهلا", "salut", "bonjour", "bonsoir"]

# How long to show the ERROR face before returning to idle.
ERROR_HOLD_SECS = 2.0


class Robot:
    def __init__(self):
        self.settings    = settings
        self.running     = True
        self._do_shutdown  = False
        self._cleaned_up = False

        self.voice_path  = str(settings.project_root / "voice.wav")
        self.answer_path = str(settings.project_root / "answer.wav")

        # Build all the parts.
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

    # ------------------------------------------------------------- main loop
    def run(self):
        log.info("Robot starting. Mock mode: %s", self.settings.mock_mode)
        if not self.assistant.ready:
            log.warning("AI is not ready — check OPENAI_API_KEY in .env.")

        self.camera.start()
        self.feed.start()      # background thread: camera preview stays live always
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
                    log.info("Stop word heard — shutting down.")
                    break

                # Reject unsupported scripts (Chinese, Cyrillic, etc.) or garbled STT output.
                if not is_supported_input(question):
                    log.info("Unsupported language or garbled input — asking to repeat.")
                    self.face.set_caption(robot=UNSUPPORTED_REPLY)
                    self._speak(UNSUPPORTED_REPLY)
                    self.face.clear_caption()
                    self._hold(RobotState.CONFUSED, 0.5)
                    self._render(RobotState.IDLE)
                    continue

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
        """Idle (with live camera preview) until a person is seen."""
        if not self.feed.available:
            # No camera — stay in idle briefly so the face still shows.
            self._hold(RobotState.IDLE, 0.5)
            return self.running

        log.info("Waiting for a person...")
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
                self._hold(RobotState.FACE_DETECTED, 0.6)
                return True
        return False

    def _listen_and_transcribe(self):
        """Record the user, transcribe, and return text — or None on failure."""
        self.face.clear_caption()
        log.info("Listening...")

        audio_file = self.recorder.record_until_silence(
            self.voice_path, on_tick=self._listen_tick)
        if audio_file is None:
            return None

        self._render(RobotState.THINKING)
        log.info("Understanding...")
        question = self.assistant.transcribe(audio_file)

        if not question:
            log.info("Empty / failed transcript — skipping.")
            self._hold(RobotState.CONFUSED, 1.0)
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
            return ("Sorry, I cannot connect right now. "
                    "Please check the internet connection."), True

        self.messages.append({"role": "assistant", "content": answer})
        log.info("Robot: %s", answer)
        return answer, self.assistant.is_fallback(answer)

    def _speak(self, text):
        """Generate and play TTS audio while animating the mouth."""
        self._render(RobotState.SPEAKING)

        audio_out = self.assistant.synthesize(text, self.answer_path)

        if audio_out is None or not os.path.exists(audio_out) \
                or os.path.getsize(audio_out) < 200:
            # No audio: show caption for a readable duration then move on.
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
            self.face.render(RobotState.SPEAKING)   # mouth animation uses time internally

        if not self.running:
            self.player.stop()

    def _post_expression(self, question, is_fallback):
        if is_fallback:
            self._hold(RobotState.CONFUSED, 0.8)
        elif self._is_greeting(question):
            self._hold(RobotState.HAPPY, 0.9)

    # --------------------------------------------------------- tiny helpers
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
        return not self.running   # returning True stops the recording

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
    def _is_greeting(text):
        t = text.lower()
        return any(w in t for w in GREETING_WORDS)

    # ------------------------------------------------------------ shutdown
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
