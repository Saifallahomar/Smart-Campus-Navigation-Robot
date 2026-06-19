"""
Colours, fonts and layout constants for the robot face.

Kept separate from face.py so the look can be tweaked without touching the
drawing logic.
"""

# --- Base palette -----------------------------------------------------------
BACKGROUND    = (10, 14, 26)        # deep navy background
FACE_BG       = (14, 18, 36)        # slightly lighter for the face zone
PANEL         = (18, 24, 42)        # caption panel background
PANEL_BORDER  = (38, 50, 80)        # divider lines
TEXT_PRIMARY  = (235, 240, 255)     # robot speech text
TEXT_SECONDARY= (150, 165, 200)     # user speech / labels
STATUS_TEXT   = (255, 255, 255)     # status badge text (always white)
MOUTH         = (240, 245, 255)
HIGHLIGHT     = (255, 255, 255)     # eye glint dot
PUPIL         = (12,  16,  30)      # dark pupil inside the eye (gaze direction)
SHUTDOWN      = (230, 80,  90)      # power button ring
SHUTDOWN_DIM  = (100, 36,  42)      # power button fill
PREVIEW_BOX   = (60,  230, 130)     # face detection rectangle (green)
PREVIEW_NONE  = (140, 155, 180)     # "looking for you" text colour
NOTICE_BG     = (40,  120, 200)     # banner background (e.g. "User is waving")
NOTICE_TEXT   = (255, 255, 255)     # banner text

# --- Per-emotion eye colour -------------------------------------------------
# Each state gets its own colour so the mood is readable at a glance.
EYE_COLORS = {
    "idle":           (0,   180, 255),  # calm blue
    "face_detected":  (60,  230, 150),  # welcoming green
    "listening":      (60,  230, 150),  # still green - attentive
    "thinking":       (255, 199,  95),  # warm yellow - processing
    "speaking":       (0,   200, 255),  # bright blue - talking
    "happy":          (95,  240, 160),  # bright green - pleased
    "confused":       (199, 146, 234),  # soft purple - uncertain
    "error":          (255,  80,  80),  # red - problem
}

# --- Per-state status badge background colour -------------------------------
BADGE_COLORS = {
    "idle":           (28,  38,  64),   # subtle muted badge: "Looking for a visitor"
    "face_detected":  (30,  100,  60),
    "listening":      (20,   90,  55),
    "thinking":       (100,  75,  20),
    "speaking":       (20,   70, 110),
    "happy":          None,
    "confused":       (70,   50,  90),
    "error":          (120,  28,  28),
}


def eye_color(state_value: str) -> tuple:
    return EYE_COLORS.get(state_value, EYE_COLORS["idle"])


def badge_color(state_value: str):
    """Return the badge background colour for a state, or None for no badge."""
    return BADGE_COLORS.get(state_value)


# --- Font size fractions (relative to the face zone height, not full screen) -
# Sized for the face zone (~230 px in portrait) so text is always readable.
FONT_STATUS_FRAC  = 0.14   # status badge text
FONT_CAPTION_FRAC = 0.13   # caption body text
FONT_LABEL_FRAC   = 0.11   # "You:" / "Robot:" labels
