"""
Speaker playback via ALSA's `aplay` (same tool the original robot used).

Plays asynchronously so the face can animate its mouth while the robot talks.

Reliability:
  - Checks the audio file exists (and has content) before trying to play it.
  - If `aplay` is missing, warns once and then stays quiet instead of logging
    the same error on every single reply.
  - `aplay_available()` lets the robot check the speaker at startup and show a
    friendly notice if it's missing.
"""

import os
import shutil
import subprocess

from src.utils.logging_setup import get_logger

log = get_logger("player")


class Player:
    def __init__(self, settings):
        self.device = settings.devices.get("speaker_device", "plughw:2,0")
        self.mock = settings.mock_mode
        self._proc = None
        self._warned_no_aplay = False   # so we warn about missing aplay only once

    def aplay_available(self) -> bool:
        """True if the `aplay` command exists on this system."""
        return shutil.which("aplay") is not None

    def play_async(self, path):
        """Start playback in the background. Returns the process, or None."""
        if self.mock:
            log.info("[mock] would play %s", path)
            return None

        # Make sure there is actually a file with audio in it.
        if not path or not os.path.exists(path) or os.path.getsize(path) < 200:
            log.warning("Nothing to play - audio file missing or empty: %s", path)
            return None

        if not self.aplay_available():
            if not self._warned_no_aplay:
                log.error("'aplay' not found - install alsa-utils "
                          "(sudo apt install alsa-utils). Robot will run without sound.")
                self._warned_no_aplay = True
            return None

        try:
            self._proc = subprocess.Popen(["aplay", "-D", self.device, path])
            return self._proc
        except Exception as exc:
            log.error("Playback failed: %s", exc)
            return None

    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
