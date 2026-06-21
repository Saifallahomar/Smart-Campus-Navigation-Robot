"""
Campus knowledge: the system prompt + an optional fast local FAQ.

The UWE knowledge text lives in data/knowledge_base.md (easy to edit without
touching code). Two structured JSON files are appended to it at startup:

  data/directions.json  — campus directions from Z Block
  data/robot_parts.json — approved electronics/robotics part explanations

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
    "You ONLY reply in English, Arabic, French, or Chinese (Mandarin) — never in any other language. "
    "English is the default language. "
    "If you are not sure about an answer, say: "
    "'I'm not sure about that. Please check uwe.ac.uk or ask at the Information Point in D Block.'"
)


class Knowledge:
    def __init__(self, settings):
        self.settings = settings
        self.use_faq = bool(settings.ai.get("use_local_faq", False))
        self.system_prompt = self._load_all()
        self.faqs = self._load_faqs()

    # ------------------------------------------------------------------ loaders

    def _load_all(self):
        """Load the main knowledge base, then append structured JSON data."""
        base = self._load_kb()
        base += self._load_directions()
        base += self._load_robot_parts()
        return base

    def _load_kb(self):
        try:
            text = self.settings.knowledge_base_path.read_text(encoding="utf-8")
            if text.strip():
                return text
            log.warning("Knowledge base is empty - using a minimal default prompt.")
        except Exception as exc:
            log.error("Could not load knowledge base (%s) - using default.", exc)
        return _DEFAULT_PROMPT

    def _load_directions(self):
        """Append campus directions from data/directions.json as a text block."""
        path = self.settings.data_dir / "directions.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("directions.json not loaded: %s", exc)
            return ""

        lines = [
            "\n\n====================================================================",
            "CAMPUS DIRECTIONS (from Z Block Engineering)",
            "====================================================================",
            f"Robot is located at: {data.get('robot_location', 'Z Block, Frenchay Campus')}",
            f"Campus map: {data.get('campus_map_url', 'uwe.ac.uk/map')}",
            f"For precise routes: {data.get('info_point', 'ask the Information Point in D Block')}",
            data.get("general_hint", ""),
            "",
        ]

        for dest in data.get("destinations", []):
            lines.append(f"To reach {dest['name']} ({dest['block']}):")
            lines.append(f"  {dest['hint']}")
            if dest.get("tip"):
                lines.append(f"  Tip: {dest['tip']}")
            lines.append("")

        lines.append(
            "IMPORTANT: If you do not have specific walking directions for a destination, "
            "say: \"I'm not fully sure of the exact route from here. Your best bet is the "
            "campus map at uwe.ac.uk/map, or ask at the Information Point in D Block — "
            "they'll point you in the right direction!\""
        )
        return "\n".join(lines)

    def _load_robot_parts(self):
        """Append robot/electronics part explanations from data/robot_parts.json."""
        path = self.settings.data_dir / "robot_parts.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.debug("robot_parts.json not loaded: %s", exc)
            return ""

        lines = [
            "\n\n====================================================================",
            "ROBOT AND ELECTRONICS PARTS — Approved Explanations",
            "====================================================================",
            "If someone asks about one of the components below, use ONLY the "
            "provided explanation. Do NOT add extra details or guess.",
            "If a component is not in this list, say: \"Hmm, I'm not sure about "
            "that specific part. For detailed info, check the engineering lab "
            "resources in Z Block or ask a technician.\"",
            "",
        ]

        for part in data.get("parts", []):
            # Show the primary name (first in the list)
            primary_name = part["names"][0].title()
            lines.append(f"{primary_name}:")
            lines.append(f"  {part['explanation']}")
            lines.append("")

        return "\n".join(lines)

    def _load_faqs(self):
        try:
            data = json.loads(self.settings.faq_path.read_text(encoding="utf-8"))
            return data.get("faqs", [])
        except Exception as exc:
            log.warning("Could not load FAQ (%s) - continuing without it.", exc)
            return []

    # ------------------------------------------------------------------ public

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
