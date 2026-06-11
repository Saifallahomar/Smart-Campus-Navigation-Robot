"""
Campus knowledge: the system prompt + an optional fast local FAQ.

The big UWE knowledge text now lives in data/knowledge_base.md (easy to edit
without touching code). The FAQ in data/faq.json can answer very common ENGLISH
questions instantly, before calling the AI - but it's OFF by default because a
fixed answer can't follow the user's spoken language.
"""

import json

from src.utils.logging_setup import get_logger

log = get_logger("knowledge")

_DEFAULT_PROMPT = (
    "You are a professional and friendly university campus guide robot. "
    "Keep answers short, clear, and helpful. Reply in the user's language."
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
