"""
Navigation video player.

Plays route MP4 videos in the face's existing camera preview area using
cv2.VideoCapture.  The face zone (eyes, mouth, status badge) continues
animating normally on the left side of the screen.

The robot stays fully responsive during playback:
  - The shutdown button works (via the on_frame_tick callback).
  - pygame events are processed on every frame.
  - The CameraFeed background thread keeps running; the camera preview
    resumes automatically once the video ends.

If the video file is missing or OpenCV is unavailable, play() returns False
and logs a clear warning — the robot continues with voice only, no crash.
"""

import time
from pathlib import Path

from src.utils.logging_setup import get_logger

log = get_logger("video_player")

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


class VideoPlayer:
    """
    Feeds MP4 video frames into the face's preview area frame-by-frame.

    Usage in robot.py::

        self.video_player = VideoPlayer(settings.project_root)

        # During a session, after speaking a directions answer:
        self.video_player.play(
            "data/videos/z_to_library.mp4",
            face=self.face,
            on_frame_tick=self._nav_video_tick,
        )
    """

    def __init__(self, project_root):
        self._root = Path(project_root)

    def play(self, rel_path: str, face, on_frame_tick=None) -> bool:
        """
        Play a video file, feeding each frame into face.set_preview().

        Args:
            rel_path:       Path relative to the project root,
                            e.g. "data/videos/z_to_library.mp4".
            face:           The Face instance (has set_preview / render).
            on_frame_tick:  Optional callable — called after each frame is
                            displayed.  Return True to stop playback early
                            (e.g. the user pressed the shutdown button).

        Returns:
            True  — video played to completion or stopped early by caller.
            False — file missing, unreadable, or OpenCV not installed.
        """
        if not _HAS_CV2:
            log.warning("OpenCV not installed — navigation videos unavailable.")
            return False

        full_path = self._root / rel_path
        if not full_path.exists():
            log.warning("Navigation video missing: %s", full_path)
            return False

        cap = cv2.VideoCapture(str(full_path))
        if not cap.isOpened():
            log.error("Could not open navigation video: %s", full_path)
            cap.release()
            return False

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_delay = 1.0 / max(1.0, fps)

        log.info("Playing navigation video: %s", rel_path)

        try:
            while True:
                t0 = time.time()

                ok, bgr = cap.read()
                if not ok:
                    break   # end of file

                # OpenCV gives BGR; pygame / face expect RGB.
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]

                # Push the video frame into the face's preview slot.
                # The face zone (eyes / mouth) is unaffected — it draws
                # separately and continues animating normally.
                face.set_preview(rgb, faces=[], frame_size=(w, h))

                # Let the caller render the frame and process UI events.
                if on_frame_tick is not None and on_frame_tick():
                    break   # caller requested stop

                # Pace to match the video's native frame rate.
                elapsed   = time.time() - t0
                remaining = max(0.0, frame_delay - elapsed)
                if remaining > 0.005:
                    time.sleep(remaining)

        except Exception as exc:
            log.error("Navigation video playback error: %s", exc)
        finally:
            cap.release()

        log.info("Navigation video finished.")
        return True
