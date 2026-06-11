"""
Colours, fonts and layout constants for the robot face.

Kept separate from face.py so the look can be tweaked without touching the
drawing logic.
"""

# --- Base palette -----------------------------------------------------------
BACKGROUND = (10, 14, 26)        # deep navy, easier on the eyes than pure black
PANEL = (20, 26, 44)             # caption panel background
PANEL_BORDER = (40, 52, 84)
TEXT_PRIMARY = (235, 240, 255)   # robot speech
TEXT_SECONDARY = (150, 165, 200) # user speech / labels
STATUS_TEXT = (200, 215, 245)
SHUTDOWN = (230, 80, 90)         # power button
SHUTDOWN_DIM = (120, 45, 50)
MOUTH = (240, 245, 255)
HIGHLIGHT = (255, 255, 255)      # eye glint

# --- Per-emotion eye colour -------------------------------------------------
# Each state gets its own friendly colour so the mood reads at a glance.
EYE_COLORS = {
    "idle": (0, 180, 255),
    "face_detected": (60, 230, 150),
    "listening": (60, 230, 150),
    "thinking": (255, 199, 95),
    "speaking": (0, 190, 255),
    "happy": (95, 240, 160),
    "confused": (199, 146, 234),
}


def eye_color(state_value: str):
    return EYE_COLORS.get(state_value, EYE_COLORS["idle"])


# --- Font sizes (scaled to screen height at runtime) ------------------------
# Expressed as a fraction of screen height so it looks right on the 7" screen
# and on a laptop window during development.
FONT_STATUS_FRAC = 0.06
FONT_CAPTION_FRAC = 0.045
FONT_LABEL_FRAC = 0.038
