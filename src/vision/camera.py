"""
Camera + face detection wrapper around Picamera2 and OpenCV Haar cascades.

Imports are guarded so the rest of the program can still be imported and the
face UI can run on a laptop (mock mode) where there is no Pi camera. If the
camera or cascade isn't available, face detection simply reports "no faces"
instead of crashing.
"""

import time

from src.utils.logging_setup import get_logger

log = get_logger("camera")

try:
    from picamera2 import Picamera2
    _HAS_PICAM = True
except Exception:
    _HAS_PICAM = False

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False


class Camera:
    def __init__(self, settings):
        v = settings.vision
        self.enabled = bool(v.get("enabled", True)) and not settings.mock_mode
        self.width = int(v.get("frame_width", 640))
        self.height = int(v.get("frame_height", 480))
        self.scale_factor = v.get("scale_factor", 1.2)
        self.min_neighbors = v.get("min_neighbors", 5)
        self.min_size = int(v.get("min_face_size", 60))
        self._cascade_path = v.get("cascade_path")

        self.available = False
        self._picam = None
        self._cascade = None

        if not self.enabled:
            log.info("Camera disabled (mock or vision.enabled=false).")
            return
        if not (_HAS_PICAM and _HAS_CV2):
            log.warning("picamera2 / OpenCV not available - running without camera.")
            return

        try:
            self._picam = Picamera2()
            self._picam.preview_configuration.main.size = (self.width, self.height)
            self._picam.preview_configuration.main.format = "RGB888"
            self._picam.configure("preview")
            self._cascade = cv2.CascadeClassifier(self._cascade_path)
            if self._cascade.empty():
                log.warning("Haar cascade not found at %s (faces won't be detected).",
                            self._cascade_path)
            self.available = True
        except Exception as exc:
            log.error("Camera init failed: %s", exc)
            self.available = False

    def start(self):
        if self.available and self._picam:
            try:
                self._picam.start()
                time.sleep(0.5)  # let the sensor settle (same as original)
                log.info("Camera started.")
            except Exception as exc:
                log.error("Camera start failed: %s", exc)
                self.available = False

    def capture_frame(self):
        """Return an RGB frame (numpy array) or None."""
        if not self.available:
            return None
        try:
            return self._picam.capture_array()
        except Exception as exc:
            log.error("Frame capture failed: %s", exc)
            return None

    def detect_faces(self, frame=None):
        """Return a list of (x, y, w, h) face boxes (possibly empty)."""
        if not self.available or self._cascade is None:
            return []
        if frame is None:
            frame = self.capture_frame()
        if frame is None:
            return []
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            faces = self._cascade.detectMultiScale(
                gray,
                scaleFactor=self.scale_factor,
                minNeighbors=self.min_neighbors,
                minSize=(self.min_size, self.min_size),
            )
            return [tuple(int(v) for v in f) for f in faces]
        except Exception as exc:
            log.error("Face detection failed: %s", exc)
            return []

    def stop(self):
        if self._picam:
            try:
                self._picam.stop()
                log.info("Camera stopped.")
            except Exception:
                pass
