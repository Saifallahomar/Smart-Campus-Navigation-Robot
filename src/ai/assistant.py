"""
OpenAI assistant: speech-to-text, chat, and text-to-speech.

Error handling:
  - Every call retries up to max_retries times with backoff.
  - Auth errors (wrong key) are caught immediately — no point retrying.
  - Rate-limit errors wait longer before retrying.
  - Connection errors are logged clearly so the log gives a useful diagnosis.
  - TTS output file is verified to have content before being returned.
"""

import os
import time

from src.utils.logging_setup import get_logger

log = get_logger("assistant")

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

# Import specific error types if available (openai >= 1.0).
try:
    from openai import APIConnectionError, AuthenticationError, RateLimitError
    _HAS_TYPED_ERRORS = True
except ImportError:
    _HAS_TYPED_ERRORS = False

# Phrases in the AI's reply that mean "I couldn't help" → show confused face.
_FALLBACK_MARKERS = [
    "i am sorry, i can't help",
    "i'm sorry, i can't help",
    "i'm not sure about that",       # matches new knowledge_base.md fallback
    "i am not sure about that",
    "لست متأكد",                      # Arabic: I'm not sure
    "je ne suis pas sûr",            # French: I'm not sure (masc)
    "je ne suis pas sûre",           # French: I'm not sure (fem)
]


class Assistant:
    def __init__(self, settings):
        ai = settings.ai
        self.chat_model       = ai.get("chat_model",        "gpt-4o-mini")
        self.transcribe_model = ai.get("transcribe_model",  "gpt-4o-mini-transcribe")
        self.tts_model        = ai.get("tts_model",         "gpt-4o-mini-tts")
        self.tts_voice        = ai.get("tts_voice",         "alloy")
        self.timeout          = ai.get("request_timeout",   30)
        self.max_retries      = int(ai.get("max_retries",   2))

        self.client = None
        if not _HAS_OPENAI:
            log.error("The 'openai' library is not installed. Run: pip install openai")
            return
        if not settings.openai_api_key:
            log.error("OPENAI_API_KEY is missing — add it to your .env file.")
            return
        try:
            self.client = OpenAI(api_key=settings.openai_api_key, timeout=self.timeout)
        except Exception as exc:
            log.error("OpenAI client init failed: %s", exc)

    @property
    def ready(self) -> bool:
        return self.client is not None

    # ----------------------------------------------------------- retry helper
    def _retry(self, func, what: str):
        """Run ``func()`` up to max_retries+1 times. Returns result or None."""
        last = None
        for attempt in range(self.max_retries + 1):
            try:
                return func()
            except Exception as exc:
                last = exc

                # Auth errors won't get better with retries.
                if _HAS_TYPED_ERRORS and isinstance(exc, AuthenticationError):
                    log.error("%s: authentication failed — check OPENAI_API_KEY in .env.", what)
                    return None

                exc_name = type(exc).__name__
                log.warning("%s failed (attempt %d/%d) [%s]: %s",
                            what, attempt + 1, self.max_retries + 1, exc_name, exc)

                if attempt < self.max_retries:
                    # Rate limit: wait longer before retrying.
                    if _HAS_TYPED_ERRORS and isinstance(exc, RateLimitError):
                        delay = 6.0
                    elif _HAS_TYPED_ERRORS and isinstance(exc, APIConnectionError):
                        delay = 3.0 * (attempt + 1)
                    else:
                        delay = 2.0 * (attempt + 1)
                    log.info("Waiting %.1fs before retry...", delay)
                    time.sleep(delay)

        log.error("%s gave up after %d attempts: %s", what, self.max_retries + 1, last)
        return None

    # ------------------------------------------------------------------- API
    def transcribe(self, audio_path: str):
        """Speech-to-text. Returns transcript string or None."""
        if not self.ready:
            return None
        if not os.path.exists(audio_path):
            log.error("Audio file not found for transcription: %s", audio_path)
            return None

        def call():
            with open(audio_path, "rb") as f:
                result = self.client.audio.transcriptions.create(
                    model=self.transcribe_model, file=f)
            return result.text.strip()

        return self._retry(call, "Transcription")

    def chat(self, messages: list):
        """Send a conversation and return the assistant reply or None."""
        if not self.ready:
            return None

        def call():
            completion = self.client.chat.completions.create(
                model=self.chat_model, messages=messages)
            return completion.choices[0].message.content

        return self._retry(call, "Chat")

    def describe_scene(self, frame_rgb, language: str = "english"):
        """
        Send ONE camera frame to the (multimodal) chat model and return a short
        spoken description, or None on failure.

        Only called on demand (when the user asks "what can you see?"). Never
        sends live video. Uses the same OpenAI key/model already configured.
        """
        if not self.ready:
            return None
        if frame_rgb is None:
            return None

        data_url = self._encode_jpeg(frame_rgb)
        if data_url is None:
            return None

        lang_name = {"english": "English", "arabic": "Arabic",
                     "french": "French"}.get(language, "English")

        def call():
            completion = self.client.chat.completions.create(
                model=self.chat_model,
                max_tokens=120,
                messages=[
                    {"role": "system", "content": (
                        "You are the eyes of a friendly campus robot. Look at the "
                        "image and say briefly what you see in 1-2 short, natural "
                        f"sentences, in {lang_name}. Be warm and concise. Do not "
                        "mention that it is an image or photo.")},
                    {"role": "user", "content": [
                        {"type": "text", "text": "What can you see right now?"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]},
                ],
            )
            return completion.choices[0].message.content.strip()

        return self._retry(call, "Vision")

    @staticmethod
    def _encode_jpeg(frame_rgb):
        """Encode an RGB numpy frame to a base64 JPEG data URL (cv2 or PIL)."""
        import base64
        data = None
        try:
            import cv2
            bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                data = buf.tobytes()
        except Exception:
            data = None
        if data is None:
            try:
                import io
                from PIL import Image
                bio = io.BytesIO()
                Image.fromarray(frame_rgb).save(bio, format="JPEG", quality=80)
                data = bio.getvalue()
            except Exception as exc:
                log.error("Could not encode camera frame for vision: %s", exc)
                return None
        return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")

    def synthesize(self, text: str, out_path: str = "answer.wav"):
        """
        Text-to-speech. Streams audio to ``out_path`` and returns the path,
        or None on failure. Verifies the file has content before returning.
        """
        if not self.ready:
            return None

        def call():
            with self.client.audio.speech.with_streaming_response.create(
                model=self.tts_model,
                voice=self.tts_voice,
                input=text,
                response_format="wav",
            ) as response:
                response.stream_to_file(out_path)

            # Verify the output file actually has audio data.
            if not os.path.exists(out_path):
                raise RuntimeError("TTS output file was not created.")
            size = os.path.getsize(out_path)
            if size < 200:
                raise RuntimeError(f"TTS output file too small ({size} bytes) — likely empty.")
            return out_path

        return self._retry(call, "Text-to-speech")

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def is_fallback(answer: str) -> bool:
        """Return True if the AI's reply is a 'can't help' fallback message."""
        if not answer:
            return False
        a = answer.lower()
        return any(m in a for m in _FALLBACK_MARKERS)
