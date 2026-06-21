"""
Optional CSV logger for student questions and robot answers.

Logs only plain text — never audio, images, video, face data, or names.
Off by default. Enable in config.json:  question_logging.enabled = true

Log file location:  logs/questions.csv
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
    "used_faq",
    "unsure",
]


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
               used_faq: bool = False, unsure: bool = False) -> None:
        """Append one Q&A row to the CSV.  Safe to call even if disabled."""
        if not self.enabled or self._path is None:
            return
        try:
            row = [
                datetime.datetime.now().isoformat(timespec="seconds"),
                language,
                question[:500],          # cap to avoid huge cells
                answer[:500],
                "yes" if used_faq else "no",
                "yes" if unsure else "no",
            ]
            with open(self._path, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
        except Exception as exc:
            log.debug("Question log write failed: %s", exc)
