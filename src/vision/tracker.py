"""
Face tracking helper.

Turns a detected face box into a smoothed, normalized (dx, dy) offset from the
centre of the frame:
    dx = -1 (far left) .. 0 (centre) .. +1 (far right)
    dy = -1 (top)      .. 0 (centre) .. +1 (bottom)

This is exactly what a future head/servo controller needs to know which way to
turn to keep looking at the person. Nothing here touches hardware.
"""


def largest_face(faces):
    """Return the biggest face box (likely the closest person), or None."""
    if not faces:
        return None
    return max(faces, key=lambda f: f[2] * f[3])


def face_offset(face, frame_w, frame_h):
    x, y, w, h = face
    cx = x + w / 2
    cy = y + h / 2
    dx = (cx - frame_w / 2) / (frame_w / 2)
    dy = (cy - frame_h / 2) / (frame_h / 2)
    return max(-1.0, min(1.0, dx)), max(-1.0, min(1.0, dy))


class FaceTracker:
    def __init__(self, smoothing=0.3, deadzone=0.08):
        self.smoothing = smoothing   # 0..1, higher = snappier
        self.deadzone = deadzone     # ignore tiny offsets near the centre
        self.x = 0.0
        self.y = 0.0

    def update(self, faces, frame_w, frame_h):
        """Feed the latest detections; return smoothed (dx, dy) or None."""
        face = largest_face(faces)
        if face is None:
            return None
        dx, dy = face_offset(face, frame_w, frame_h)
        self.x += (dx - self.x) * self.smoothing
        self.y += (dy - self.y) * self.smoothing
        ox = 0.0 if abs(self.x) < self.deadzone else self.x
        oy = 0.0 if abs(self.y) < self.deadzone else self.y
        return ox, oy

    def reset(self):
        self.x = 0.0
        self.y = 0.0
