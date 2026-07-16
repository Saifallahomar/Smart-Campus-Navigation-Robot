"""
Microphone recording with simple voice activity detection (VAD).

Records until the person stops talking (a short silence) or the maximum time is
reached - the same approach as the original robot, just wrapped safely. Imports
are guarded so the program still runs in mock mode without audio hardware.
"""

from src.utils.logging_setup import get_logger

log = get_logger("recorder")

try:
    import numpy as np
    import sounddevice as sd
    from scipy.io.wavfile import write as wav_write
    _HAS_AUDIO = True
except Exception:
    _HAS_AUDIO = False


class Recorder:
    def __init__(self, settings):
        a = settings.audio
        self.sample_rate = int(a.get("sample_rate", 16000))
        self.chunk_seconds = float(a.get("chunk_seconds", 0.2))
        self.chunk_samples = int(self.sample_rate * self.chunk_seconds)
        self.voice_threshold = a.get("voice_threshold", 500)
        self.silence_to_stop = a.get("silence_to_stop", 0.9)
        self.max_record_seconds = a.get("max_record_seconds", 10)
        # How long to wait for speech to BEGIN before giving up and returning None.
        # Without this, the recorder blocks indefinitely when the mic threshold is
        # never crossed (too high, person too quiet, or mic not picking up audio).
        self.max_initial_wait_seconds = float(a.get("max_initial_wait_seconds", 6.0))
        self.device = settings.devices.get("mic_device", 1)

        self.available = _HAS_AUDIO and not settings.mock_mode
        if not self.available:
            log.warning("Microphone recording unavailable (mock or missing libraries).")

    def record_until_silence(self, filename="voice.wav", on_tick=None):
        """
        Record until silence. ``on_tick(volume, started)`` is called each chunk;
        return True from it to stop early (e.g. user pressed shutdown).
        Returns the saved filename, or None if nothing was recorded.
        """
        if not self.available:
            return None

        frames = []
        started = False
        silence_time = 0.0
        total_time = 0.0
        pre_speech_time = 0.0   # time spent waiting for speech to begin

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                device=self.device,
            ) as stream:
                while True:
                    audio, _ = stream.read(self.chunk_samples)
                    volume = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))

                    if volume > self.voice_threshold:
                        started = True
                        frames.append(audio.copy())
                        silence_time = 0.0
                        total_time += self.chunk_seconds
                    elif started:
                        frames.append(audio.copy())
                        silence_time += self.chunk_seconds
                        total_time += self.chunk_seconds
                        if silence_time >= self.silence_to_stop:
                            break
                    else:
                        # Still waiting for speech to begin.
                        pre_speech_time += self.chunk_seconds
                        if pre_speech_time >= self.max_initial_wait_seconds:
                            log.info("No speech heard after %.1fs — returning to caller.",
                                     pre_speech_time)
                            break

                    if on_tick is not None and on_tick(volume, started):
                        log.info("Recording stopped early by caller.")
                        break

                    if started and total_time >= self.max_record_seconds:
                        log.info("Maximum recording time reached.")
                        break
        except Exception as exc:
            log.error("Recording failed: %s", exc)
            return None

        if not frames:
            return None

        try:
            recorded = np.concatenate(frames, axis=0)
            wav_write(filename, self.sample_rate, recorded)
            return filename
        except Exception as exc:
            log.error("Saving recording failed: %s", exc)
            return None
