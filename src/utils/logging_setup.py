"""
Simple logging setup for the robot.

Logs go to the console (so you still see what's happening when running by hand)
AND to a rotating file in logs/robot.log (so you can review test sessions later).
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir, level=logging.INFO) -> logging.Logger:
    """Configure the root 'robot' logger once. Safe to call multiple times."""
    global _CONFIGURED
    logger = logging.getLogger("robot")

    if _CONFIGURED:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console output.
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # Rotating file output (best effort - never crash if disk/path fails).
    try:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "robot.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Could not create log file: %s", exc)

    _CONFIGURED = True
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """Get a child logger, e.g. get_logger('camera') -> 'robot.camera'."""
    return logging.getLogger("robot" + (f".{name}" if name else ""))
