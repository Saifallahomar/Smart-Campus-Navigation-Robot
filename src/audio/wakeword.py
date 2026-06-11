"""
Optional wake word ("Hey robot") before the robot starts listening.

DISABLED BY DEFAULT - the robot already uses face detection to know when to
listen. Turn it on in config.json (wake_word.enabled = true) if you want an
extra spoken trigger.

Engines:
  - "porcupine": real, accurate wake word (needs `pip install pvporcupine`, a
    PORCUPINE_ACCESS_KEY in .env, and keyword .ppn files listed in config).
  - "energy": placeholder that currently passes through immediately (kept so the
    structure is ready; a full energy detector can be added later).
"""

from src.utils.logging_setup import get_logger

log = get_logger("wakeword")


class WakeWord:
    def __init__(self, settings):
        cfg = settings.wake_word
        self.enabled = bool(cfg.get("enabled", False)) and not settings.mock_mode
        self.engine = cfg.get("engine", "energy")
        self._porcupine = None
        self._warned_energy = False

        if self.enabled and self.engine == "porcupine":
            self._init_porcupine(settings)

        if self.enabled:
            log.info("Wake word enabled (engine=%s).", self.engine)

    def _init_porcupine(self, settings):
        try:
            import pvporcupine
            key = settings.porcupine_access_key
            paths = settings.wake_word.get("porcupine_keyword_paths", [])
            if not key or not paths:
                log.warning("Porcupine needs PORCUPINE_ACCESS_KEY and keyword paths - disabling.")
                self.enabled = False
                return
            self._porcupine = pvporcupine.create(access_key=key, keyword_paths=paths)
        except Exception as exc:
            log.error("Porcupine init failed (%s) - disabling wake word.", exc)
            self.enabled = False

    def wait_for_wake(self, on_tick=None):
        """
        Block until the wake word is heard. Returns True when triggered (or
        immediately if disabled). ``on_tick`` may return True to cancel.
        """
        if not self.enabled:
            return True
        if self.engine == "porcupine" and self._porcupine is not None:
            return self._wait_porcupine(on_tick)
        if not self._warned_energy:
            log.warning("Energy wake word is a placeholder - passing through.")
            self._warned_energy = True
        return True

    def _wait_porcupine(self, on_tick):
        try:
            import sounddevice as sd
            frame_len = self._porcupine.frame_length
            rate = self._porcupine.sample_rate
            with sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                                blocksize=frame_len) as stream:
                while True:
                    pcm, _ = stream.read(frame_len)
                    if self._porcupine.process(pcm[:, 0]) >= 0:
                        log.info("Wake word detected.")
                        return True
                    if on_tick is not None and on_tick():
                        return False
        except Exception as exc:
            log.error("Wake word listening failed (%s) - passing through.", exc)
            return True

    def close(self):
        if self._porcupine is not None:
            try:
                self._porcupine.delete()
            except Exception:
                pass
