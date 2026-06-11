"""
OpenAI assistant: speech-to-text, chat, and text-to-speech.

Every network call is wrapped with retries and error handling so a hiccup makes
the robot recover gracefully instead of crashing.
"""

import time

from src.utils.logging_setup import get_logger

log = get_logger("assistant")

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except Exception:
    _HAS_OPENAI = False

# Phrases that mean "I couldn't help" -> used to show a confused face.
_FALLBACK_MARKERS = ["i am sorry, i can't help", "i'm sorry, i can't help"]


class Assistant:
    def __init__(self, settings):
        ai = settings.ai
        self.chat_model = ai.get("chat_model", "gpt-4o-mini")
        self.transcribe_model = ai.get("transcribe_model", "gpt-4o-mini-transcribe")
        self.tts_model = ai.get("tts_model", "gpt-4o-mini-tts")
        self.tts_voice = ai.get("tts_voice", "alloy")
        self.timeout = ai.get("request_timeout", 30)
        self.max_retries = int(ai.get("max_retries", 2))

        self.client = None
        if not _HAS_OPENAI:
            log.error("The 'openai' library is not installed (pip install openai).")
            return
        if not settings.openai_api_key:
            log.error("OPENAI_API_KEY is missing - add it to your .env file.")
            return
        try:
            self.client = OpenAI(api_key=settings.openai_api_key, timeout=self.timeout)
        except Exception as exc:
            log.error("OpenAI client init failed: %s", exc)

    @property
    def ready(self):
        return self.client is not None

    def _retry(self, func, what):
        last = None
        for attempt in range(self.max_retries + 1):
            try:
                return func()
            except Exception as exc:
                last = exc
                log.warning("%s failed (attempt %d/%d): %s",
                            what, attempt + 1, self.max_retries + 1, exc)
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        log.error("%s gave up: %s", what, last)
        return None

    def transcribe(self, audio_path):
        if not self.ready:
            return None

        def call():
            with open(audio_path, "rb") as f:
                result = self.client.audio.transcriptions.create(
                    model=self.transcribe_model, file=f)
            return result.text.strip()

        return self._retry(call, "Transcription")

    def chat(self, messages):
        if not self.ready:
            return None

        def call():
            completion = self.client.chat.completions.create(
                model=self.chat_model, messages=messages)
            return completion.choices[0].message.content

        return self._retry(call, "Chat")

    def synthesize(self, text, out_path="answer.wav"):
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
            return out_path

        return self._retry(call, "Text-to-speech")

    @staticmethod
    def is_fallback(answer):
        if not answer:
            return False
        a = answer.lower()
        return any(m in a for m in _FALLBACK_MARKERS)
