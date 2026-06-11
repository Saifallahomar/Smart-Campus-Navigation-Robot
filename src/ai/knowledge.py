"""
Campus knowledge: the system prompt + an optional fast local FAQ.

The UWE knowledge text lives in data/knowledge_base.md (easy to edit without
touching code). The language policy (English / Arabic / French only) is defined
there so the AI always follows it.

The FAQ in data/faq.json can answer very common ENGLISH questions instantly,
before calling the AI — off by default because fixed answers cannot follow the
user's language.

Language detection (filtering unsupported scripts before the AI call) is handled
by src/ai/language.py and applied in src/core/robot.py.
"""

import json

from src.utils.logging_setup import get_logger

log = get_logger("knowledge")

_DEFAULT_PROMPT = (
    "You are a professional and friendly university campus guide robot at UWE Bristol. "
    "Keep answers short, clear, and helpful. "
    "You ONLY reply in English, Arabic, or French — never in any other language. "
    "English is the default language. "
    "If you are not sure about an answer, say: "
    "'I'm not sure about that. Please check uwe.ac.uk or ask at the Information Point in D Block.'"
)


class Knowledge:
    def __init__(self, settings):
        self.settings = settings
        self.use_faq = bool(settings.ai.get("use_local_faq", False))
        self.system_prompt = self._load_kb()
        self.faqs = self._load_faqs()

    def _load_kb(self):
        try:
            text = self.settings.knowledge_base_path.read_text(encoding="utf-8")
            if text.strip():
                return text
            log.warning("Knowledge base is empty - using a minimal default prompt.")
        except Exception as exc:
            log.error("Could not load knowledge base (%s) - using default.", exc)
        return _DEFAULT_PROMPT

    def _load_faqs(self):
        try:
            data = json.loads(self.settings.faq_path.read_text(encoding="utf-8"))
            return data.get("faqs", [])
        except Exception as exc:
            log.warning("Could not load FAQ (%s) - continuing without it.", exc)
            return []

    def match_faq(self, question):
        """Return a quick local answer if confident, else None."""
        if not self.use_faq or not self.faqs:
            return None
        q = question.lower()
        for entry in self.faqs:
            patterns = [p.lower() for p in entry.get("patterns", [])]
            if patterns and all(p in q for p in patterns):
                log.info("FAQ matched: %s", patterns)
                return entry.get("answer")
        return None

    def build_messages(self):
        """Fresh conversation seeded with the system prompt."""
        return [{"role": "system", "content": self.system_prompt}]
