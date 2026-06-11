#!/usr/bin/env python3
"""
Smart Campus Navigation Robot - entry point.

Run it with:
    python run.py

This sets up logging and starts the robot. All the real work lives in
src/core/robot.py and the modules under src/.
"""

import sys
from pathlib import Path

# Allow running from any folder by putting the project root on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import settings           # noqa: E402
from src.core.robot import Robot               # noqa: E402
from src.utils.logging_setup import get_logger, setup_logging  # noqa: E402


def main():
    setup_logging(settings.log_dir)
    log = get_logger()
    log.info("=== Smart Campus Navigation Robot ===")

    try:
        robot = Robot()
        robot.run()
    except Exception:
        # Last-resort safety net so a startup error is logged, not silent.
        log.exception("Robot crashed with an unexpected error.")
        sys.exit(1)


if __name__ == "__main__":
    main()
