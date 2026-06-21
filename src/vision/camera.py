"""
Camera + face detection wrapper around Picamera2 and OpenCV Haar cascades.

Imports are guarded so the rest of the program can still be imported and the
face UI can run on a laptop (mock mode) where there is no Pi camera. If the
camera or cascade isn't available, face detection simply reports "no faces"
instead of crashing.

CameraFeed
----------
A background thread that continuously captures frames and runs face detection
so the camera preview stays live regardless of what the robot is doing
(listening, thinking, speaking, etc.). Without this thread, the preview would
freeze on the last frame captured while waiting for a face.
"""

import threading
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
        self.width  = int(v.get("frame_width",  640))
        self.height = int(v.get("frame_height", 480))
        self.scale_factor  = v.get("scale_factor",  1.2)
        self.min_neighbors = v.get("min_neighbors", 5)
        self.min_size      = int(v.get("min_face_size", 60))
        self._cascade_path = v.get("cascade_path")

        self.available = False
        self._picam   = None
        self._cascade = None

        if not self.enabled:
            log.info("Camera disabled (mock or vision.enabled=false).")
            return
        if not (_HAS_PICAM and _HAS_CV2):
            log.warning("picamera2 / OpenCV not available - running without camera.")
            return

        # Optional quality controls (e.g. AwbMode, Brightness) — applied after start().
        # Strip _comment keys so JSON comment fields are ignored safely.
        raw_controls = v.get("camera_controls") or {}
        self._cam_controls = {k: val for k, val in raw_controls.items()
                              if not k.startswith("_")}

        try:
            self._picam = Picamera2()
            self._picam.preview_configuration.main.size   = (self.width, self.height)
            self._picam.preview_configuration.main.format = "RGB888"
            self._picam.configure("preview")
            self._cascade = cv2.CascadeClassifier(self._cascade_path)
            if self._cascade.empty():
                log.warning("Haar cascade not found at %s (face detection off).",
                            self._cascade_path)
            self.available = True
        except Exception as exc:
            log.error("Camera init failed: %s", exc)
            self.available = False

    def start(self):
        if self.available and self._picam:
            try:
                self._picam.start()
                time.sleep(0.5)   # let the sensor settle (same as original)
                log.info("Camera started.")
            except Exception as exc:
                log.error("Camera start failed: %s", exc)
                self.available = False
                return
            # Apply optional quality controls (AWB mode, brightness, etc.).
            # Wrapped separately so a control failure never disables the camera.
            if self._cam_controls:
                try:
                    self._picam.set_controls(self._cam_controls)
                    log.info("Camera controls applied: %s", self._cam_controls)
                except Exception as exc:
                    log.warning("Camera controls not applied (%s) — continuing.", exc)

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
            gray  = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
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


class CameraFeed:
    """
    Runs camera capture + face detection in a daemon background thread.

    By updating continuously the preview stays live in every robot state — not
    just while waiting for a face. The main loop reads ``frame`` and ``faces``
    at any time without blocking.

    Usage::

        feed = CameraFeed(camera, fps=15)
        feed.start()
        # later, in any state:
        frame = feed.frame     # latest RGB numpy array (or None)
        faces = feed.faces     # latest [(x,y,w,h), ...] list
        if feed.has_face: ...
        feed.stop()
    """

    def __init__(self, camera: Camera, fps: int = 15):
        self._cam      = camera
        self._interval = 1.0 / max(1, fps)
        self._frame    = None
        self._faces: list = []
        self._lock     = threading.Lock()
        self._thread   = None
        self._running  = False

    @property
    def available(self) -> bool:
        return self._cam.available

    def start(self):
        if not self._cam.available:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True, name="camera-feed")
        self._thread.start()
        log.info("Camera feed thread started (target %.0f fps).", 1.0 / self._interval)

    def _run(self):
        while self._running:
            t0 = time.time()
            try:
                frame = self._cam.capture_frame()
                if frame is not None:
                    faces = self._cam.detect_faces(frame)
                    with self._lock:
                        self._frame = frame
                        self._faces = faces
            except Exception as exc:
                log.debug("Camera feed error: %s", exc)
            elapsed   = time.time() - t0
            remaining = max(0.0, self._interval - elapsed)
            if remaining > 0:
                time.sleep(remaining)

    @property
    def frame(self):
        """Latest RGB numpy frame, or None."""
        with self._lock:
            return self._frame

    @property
    def faces(self) -> list:
        """Latest list of (x, y, w, h) face boxes."""
        with self._lock:
            return list(self._faces)

    @property
    def has_face(self) -> bool:
        with self._lock:
            return len(self._faces) > 0

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        log.info("Camera feed thread stopped.")
