"""
Optional CSV logger for student questions and robot answers.

Logs only plain text — never audio, images, video, face data, or names.
Off by default. Enable in config.json:  question_logging.enabled = true

Log file location:  logs/questions.csv
Columns: timestamp, detected_language, user_question, robot_answer,
         category, used_camera, unsure
"""

import csv
import datetime
from pathlib import Path

from src.utils.logging_setup import get_logger

log = get_logger("question_logger")

_FIELDS = [
    "timestamp",
    "detected_language",
    "user_question",
    "robot_answer",
    "category",
    "used_camera",
    "unsure",
]

# Simple keyword-based category inference — keeps robot.py clean.
_CATEGORY_RULES = [
    (["where", "direction", "how do i get", "how to get", "find", "located", "location",
      "block", "room", "floor", "building", "map"],          "directions"),
    (["what time", "when", "open", "close", "hour", "schedule", "timetable"],
                                                              "schedule"),
    (["event", "show and tell", "scholarship", "open day", "activity"],
                                                              "event"),
    (["course", "module", "degree", "programme", "program", "study",
      "engineering", "mechatronics", "computer science"],     "courses"),
    (["help", "support", "service", "wellbeing", "health", "disability",
      "finance", "bursary", "accommodation", "library"],      "support"),
    (["what can you see", "what do you see", "describe", "camera",
      "can you see"],                                         "vision"),
]


def _infer_category(question: str) -> str:
    q = question.lower()
    for keywords, category in _CATEGORY_RULES:
        if any(kw in q for kw in keywords):
            return category
    return "general"


class QuestionLogger:
    def __init__(self, settings):
        cfg = settings.get("question_logging") or {}
        self.enabled = bool(cfg.get("enabled", False))
        self._path: Path | None = None

        if not self.enabled:
            return

        log_dir = settings.log_dir
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.warning("Cannot create log directory for question log: %s", exc)
            self.enabled = False
            return

        self._path = log_dir / "questions.csv"

        # Write the header row only if the file is new / empty.
        if not self._path.exists() or self._path.stat().st_size == 0:
            try:
                with open(self._path, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(_FIELDS)
                log.info("Question log started: %s", self._path)
            except Exception as exc:
                log.warning("Could not create question log: %s", exc)
                self.enabled = False

    def record(self, language: str, question: str, answer: str,
               used_camera: bool = False, unsure: bool = False) -> None:
        """Append one Q&A row to the CSV. Safe to call even if disabled."""
        if not self.enabled or self._path is None:
            return
        try:
            row = [
                datetime.datetime.now().isoformat(timespec="seconds"),
                language,
                question[:500],          # cap to avoid huge cells
                answer[:500],
                _infer_category(question),
                "yes" if used_camera else "no",
                "yes" if unsure else "no",
            ]
            with open(self._path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
            log.info("Question logged [%s | %s]: %.60s…",
                     language, _infer_category(question), question)
        except Exception as exc:
            log.debug("Question log write failed (robot continues): %s", exc)
