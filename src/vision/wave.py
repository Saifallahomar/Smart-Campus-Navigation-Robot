"""
Lightweight wave / motion detection for the campus robot.

HOW IT WORKS
============
Each time update() is called, the detector compares the current camera frame
to the previous one — specifically in the region ABOVE the detected face,
which is where a raised or waving hand appears.

If the frame-difference in that zone exceeds a threshold for several
consecutive frames, a wave event is reported.

LIMITATIONS
===========
This detects ANY sustained fast motion above the face, not only waves.
Background movement (someone walking behind the subject) or a sudden lighting
change can trigger a false positive. In a typical indoor campus lobby with
stable lighting the false-positive rate is low enough to be useful.

To reduce false positives, tune:
  motion_threshold   — higher = needs stronger motion (default 30)
  min_motion_frames  — higher = motion must be sustained longer (default 8)
  cooldown           — minimum seconds between consecutive events (default 3)

FUTURE UPGRADE
==============
Replace the frame-difference core with MediaPipe Hands or a trained gesture
classifier. The public update() / reset() interface stays the same so the
rest of the robot code does not need to change.

Wave detection is OFF by default (wave_detection.enabled = false in config.json).
"""

import time
from typing import List, Optional, Tuple

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


class WaveDetector:
    """
    Motion-based wave gesture detector.

    Call update(frame, faces) every camera frame.
    Returns True (once per wave event) when a wave is confirmed.
    Call reset() when the robot enters idle so stale state is cleared.
    """

    def __init__(
        self,
        enabled: bool = False,
        motion_threshold: float = 30.0,
        min_motion_frames: int = 8,
        cooldown: float = 3.0,
    ):
        self.enabled = enabled
        self._threshold = motion_threshold
        self._min_frames = min_motion_frames
        self._cooldown = cooldown

        self._prev_zone: Optional[object] = None
        self._motion_count: int = 0
        self._last_wave_time: float = 0.0

    # ------------------------------------------------------------------ public

    def reset(self) -> None:
        """Clear motion history — call when entering idle so old frames don't linger."""
        self._prev_zone = None
        self._motion_count = 0

    def update(
        self,
        frame_rgb,
        face_bboxes: List[Tuple[int, int, int, int]],
    ) -> bool:
        """
        Process one camera frame.  Returns True when a wave is detected.

        frame_rgb  : numpy uint8 array shape (H, W, 3), RGB colour.
        face_bboxes: list of (x, y, w, h) bounding boxes from face detection.
                     An empty list means no face is visible.
        """
        if not self.enabled or not _HAS_NUMPY or frame_rgb is None:
            return False

        # Only detect waves when a face is already visible (person is engaged).
        if not face_bboxes:
            self._prev_zone = None
            self._motion_count = 0
            return False

        # Respect cooldown between consecutive wave events.
        if (time.time() - self._last_wave_time) < self._cooldown:
            return False

        try:
            return self._check_motion(frame_rgb, face_bboxes)
        except Exception:
            # Never let wave detection crash the main loop.
            return False

    # ----------------------------------------------------------------- private

    def _check_motion(self, frame_rgb, face_bboxes) -> bool:
        # Grayscale: average the R, G, B channels.
        gray = np.mean(frame_rgb, axis=2).astype(np.uint8)

        # Wave zone = all rows ABOVE the topmost detected face.
        top_face_y = min(y for (x, y, fw, fh) in face_bboxes)
        zone_bottom = max(0, top_face_y)

        if zone_bottom < 20:
            # Face too close to the top — not enough room for a hand above it.
            return False

        zone = gray[:zone_bottom, :]  # shape (zone_bottom, width)

        if self._prev_zone is not None and self._prev_zone.shape == zone.shape:
            diff = float(
                np.mean(np.abs(zone.astype(np.int16) - self._prev_zone.astype(np.int16)))
            )

            if diff > self._threshold:
                self._motion_count += 1
            else:
                # Decay: motion must be sustained, not just a single flicker.
                self._motion_count = max(0, self._motion_count - 2)

            if self._motion_count >= self._min_frames:
                # Confirmed wave event.
                self._last_wave_time = time.time()
                self._motion_count = 0
                self._prev_zone = zone.copy()
                return True

        self._prev_zone = zone.copy()
        return False
