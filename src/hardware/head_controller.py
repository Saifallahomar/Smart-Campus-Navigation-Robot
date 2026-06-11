"""
Head movement controller (preparation only - NO motors yet).

Today this just records where the head *would* turn to follow a person, and logs
it occasionally. When servos are added later, subclass HeadController and
implement ``_apply(pan, tilt)`` to drive them - the rest of the robot code won't
need to change.

    pan  : -1.0 (full left)  .. +1.0 (full right)
    tilt : -1.0 (full down)  .. +1.0 (full up)
"""

import time

from src.utils.logging_setup import get_logger

log = get_logger("head")


class HeadController:
    def __init__(self, settings=None, step=0.5):
        self.connected = False  # becomes True in a real servo subclass
        self.step = step        # how strongly to react to an offset
        self.pan = 0.0
        self.tilt = 0.0
        self._last_log = 0.0

    def aim(self, dx, dy):
        """Nudge the head toward a person at normalized offset (dx, dy)."""
        self.pan = max(-1.0, min(1.0, self.pan + dx * self.step))
        # Image y grows downward, so invert for an intuitive tilt.
        self.tilt = max(-1.0, min(1.0, self.tilt - dy * self.step))
        self._apply(self.pan, self.tilt)

    def center(self):
        self.pan = 0.0
        self.tilt = 0.0
        self._apply(0.0, 0.0)

    def _apply(self, pan, tilt):
        """No-op placeholder. Override in a servo subclass."""
        now = time.time()
        if now - self._last_log > 1.0:  # throttle so logs stay readable
            log.debug("Head would aim pan=%.2f tilt=%.2f (no servo connected).",
                      pan, tilt)
            self._last_log = now
