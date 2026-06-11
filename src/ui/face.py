"""
The robot's animated face (pygame).

Draws friendly eyes and a mouth that change with the robot's emotion/state,
blinks naturally, bobs gently while idle, and shows:
  - a status label ("Listening...", "Thinking...", ...)
  - captions of what the user said and what the robot is replying
  - a small live camera preview
  - a safe-shutdown power button (also Esc on a keyboard)

All drawing is best-effort: if a fancy feature (anti-aliasing, preview) fails it
falls back gracefully instead of crashing the robot.
"""

import math
import random
import time

import pygame

try:
    import pygame.gfxdraw as gfxdraw  # nicer anti-aliased shapes
    _HAS_GFX = True
except Exception:  # pragma: no cover - depends on the pygame build
    _HAS_GFX = False

from src.ui import theme
from src.utils.logging_setup import get_logger

log = get_logger("face")


class Face:
    def __init__(self, settings):
        self.settings = settings
        ui = settings.ui
        self.fps = int(ui.get("fps", 30))
        self.show_captions = bool(ui.get("show_captions", True))

        pygame.display.init()
        pygame.font.init()

        if ui.get("fullscreen", True):
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode((800, 480))
        pygame.display.set_caption("Smart Campus Robot")
        try:
            pygame.mouse.set_visible(False)
        except Exception:
            pass

        self.width, self.height = self.screen.get_size()
        self.clock = pygame.time.Clock()

        # Fonts scaled to the screen so it looks right on the 7" panel.
        self.font_status = pygame.font.SysFont(
            "Arial", int(self.height * theme.FONT_STATUS_FRAC), bold=True)
        self.font_caption = pygame.font.SysFont(
            "Arial", int(self.height * theme.FONT_CAPTION_FRAC))
        self.font_label = pygame.font.SysFont(
            "Arial", int(self.height * theme.FONT_LABEL_FRAC), bold=True)

        # Animation timers.
        self._t0 = time.time()
        self._next_blink = time.time() + random.uniform(2, 5)
        self._blinking_until = 0.0

        # On-screen text / preview.
        self._user_text = ""
        self._robot_text = ""
        self._status = ""
        self._preview = None

        # Caption panel + shutdown button geometry.
        self.caption_h = int(self.height * 0.26) if self.show_captions else 0
        self.face_area = pygame.Rect(0, 0, self.width, self.height - self.caption_h)

        btn = int(min(self.width, self.height) * 0.10)
        margin = int(btn * 0.4)
        self._shutdown_rect = pygame.Rect(
            self.width - btn - margin, self.height - btn - margin, btn, btn)

        log.info("Face ready (%dx%d, gfx=%s).", self.width, self.height, _HAS_GFX)

    # ------------------------------------------------------------------ setters
    def set_caption(self, user=None, robot=None):
        if user is not None:
            self._user_text = user
        if robot is not None:
            self._robot_text = robot

    def clear_caption(self):
        self._user_text = ""
        self._robot_text = ""

    def set_status(self, text):
        self._status = text or ""

    def set_preview(self, frame_rgb):
        """Store the latest camera frame (numpy RGB HxWx3) for the thumbnail."""
        if frame_rgb is None:
            self._preview = None
            return
        try:
            import numpy as np
            self._preview = pygame.surfarray.make_surface(np.swapaxes(frame_rgb, 0, 1))
        except Exception:
            self._preview = None

    # ------------------------------------------------------------------ events
    def pump_events(self):
        """Return a list of high-level events: 'quit', 'shutdown'."""
        events = []
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                events.append("quit")
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    events.append("quit")
                elif e.key == pygame.K_s:
                    events.append("shutdown")
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if self._shutdown_rect.collidepoint(e.pos):
                    events.append("shutdown")
        return events

    # ------------------------------------------------------------------ render
    def render(self, state, mouth_open=False):
        now = time.time()
        sv = state.value if hasattr(state, "value") else str(state)

        self.screen.fill(theme.BACKGROUND)

        color = theme.eye_color(sv)
        openness = self._eye_openness(now)
        bob = math.sin((now - self._t0) * 1.5) * (self.height * 0.006)

        eye_y = self.face_area.height * 0.42 + bob
        eye_rx = self.width * 0.085
        eye_ry = self.height * 0.12
        gap = self.width * 0.20
        cx = self.width / 2
        self._draw_eye(cx - gap, eye_y, eye_rx, eye_ry, color, openness)
        self._draw_eye(cx + gap, eye_y, eye_rx, eye_ry, color, openness)

        self._draw_mouth(sv, mouth_open, bob)

        if self._status:
            self._draw_status(self._status)
        if self.show_captions:
            self._draw_captions()
        if self._preview is not None:
            self._draw_preview()
        self._draw_shutdown_button()

        pygame.display.flip()
        self.clock.tick(self.fps)

    # ------------------------------------------------------------- drawing bits
    def _eye_openness(self, now):
        """Return 0 (closed) .. 1 (open), producing a natural blink."""
        if self._blinking_until == 0.0 and now >= self._next_blink:
            self._blinking_until = now + 0.18
        if self._blinking_until:
            remaining = self._blinking_until - now
            if remaining <= 0:
                self._blinking_until = 0.0
                self._next_blink = now + random.uniform(2.5, 6.0)
                return 1.0
            total = 0.18
            elapsed = total - remaining
            half = total / 2
            return 1.0 - (elapsed / half) if elapsed < half else (elapsed - half) / half
        return 1.0

    def _draw_eye(self, cx, cy, rx, ry, color, openness):
        cx, cy, rx = int(cx), int(cy), int(rx)
        if openness < 0.12:  # closed -> a soft line
            pygame.draw.line(self.screen, color, (cx - rx, cy), (cx + rx, cy),
                             max(4, int(ry * 0.25)))
            return
        ry_eff = max(3, int(ry * openness))
        if _HAS_GFX:
            gfxdraw.filled_ellipse(self.screen, cx, cy, rx, ry_eff, color)
            gfxdraw.aaellipse(self.screen, cx, cy, rx, ry_eff, color)
        else:
            pygame.draw.ellipse(self.screen, color, (cx - rx, cy - ry_eff, rx * 2, ry_eff * 2))
        # Eye glint for a friendlier look.
        gx, gy = int(cx - rx * 0.3), int(cy - ry_eff * 0.4)
        gr = max(2, int(rx * 0.18))
        if _HAS_GFX:
            gfxdraw.filled_circle(self.screen, gx, gy, gr, theme.HIGHLIGHT)
            gfxdraw.aacircle(self.screen, gx, gy, gr, theme.HIGHLIGHT)
        else:
            pygame.draw.circle(self.screen, theme.HIGHLIGHT, (gx, gy), gr)

    def _draw_mouth(self, state_value, mouth_open, bob=0.0):
        cx = self.width // 2
        my = int(self.face_area.height * 0.66 + bob)
        w = int(self.width * 0.16)
        h = int(self.height * 0.12)
        color = theme.MOUTH

        if state_value == "speaking" and mouth_open:
            rx, ry = int(w * 0.6), int(h * 0.6)
            if _HAS_GFX:
                gfxdraw.filled_ellipse(self.screen, cx, my, rx, ry, color)
                gfxdraw.aaellipse(self.screen, cx, my, rx, ry, color)
            else:
                pygame.draw.ellipse(self.screen, color, (cx - rx, my - ry, rx * 2, ry * 2))
        elif state_value == "confused":
            # slightly wavy / tilted line
            pygame.draw.line(self.screen, color,
                             (cx - w * 0.6, my), (cx + w * 0.6, my - h * 0.3),
                             max(5, int(h * 0.16)))
        elif state_value in ("thinking", "listening"):
            # small neutral line
            pygame.draw.line(self.screen, color,
                             (cx - w * 0.4, my), (cx + w * 0.4, my),
                             max(5, int(h * 0.16)))
        else:
            # idle / happy / face_detected -> friendly smile
            rect = pygame.Rect(cx - w, my - h, w * 2, h * 2)
            pygame.draw.arc(self.screen, color, rect, 3.4, 6.0, max(6, int(h * 0.18)))

    def _draw_status(self, text):
        surf = self.font_status.render(text, True, theme.STATUS_TEXT)
        rect = surf.get_rect(center=(self.width // 2, int(self.height * 0.10)))
        self.screen.blit(surf, rect)

    def _draw_captions(self):
        panel = pygame.Rect(0, self.height - self.caption_h, self.width, self.caption_h)
        pygame.draw.rect(self.screen, theme.PANEL, panel)
        pygame.draw.line(self.screen, theme.PANEL_BORDER,
                         (0, panel.top), (self.width, panel.top), 2)
        pad = int(self.width * 0.04)
        y = panel.top + int(self.caption_h * 0.10)
        max_w = self.width - pad * 2
        if self._user_text:
            y = self._blit_labeled("You:", self._user_text, pad, y, max_w,
                                   theme.TEXT_SECONDARY, max_lines=1)
        if self._robot_text:
            self._blit_labeled("Robot:", self._robot_text, pad, y, max_w,
                               theme.TEXT_PRIMARY, max_lines=2)

    def _blit_labeled(self, label, text, x, y, max_w, color, max_lines=2):
        lbl = self.font_label.render(label, True, color)
        self.screen.blit(lbl, (x, y))
        lines = self._wrap(text, self.font_caption, max_w)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip() + "..."
        ty = y + lbl.get_height() + int(self.height * 0.004)
        for ln in lines:
            s = self.font_caption.render(ln, True, color)
            self.screen.blit(s, (x, ty))
            ty += s.get_height() + 2
        return ty + int(self.height * 0.01)

    def _wrap(self, text, font, max_w):
        lines, cur = [], ""
        for word in text.split():
            test = (cur + " " + word).strip()
            if font.size(test)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def _draw_preview(self):
        tw = int(self.width * 0.16)
        th = int(tw * 0.75)
        try:
            thumb = pygame.transform.smoothscale(self._preview, (tw, th))
        except Exception:
            return
        x = self.width - tw - int(self.width * 0.02)
        y = int(self.height * 0.03)
        self.screen.blit(thumb, (x, y))
        pygame.draw.rect(self.screen, theme.PANEL_BORDER, (x, y, tw, th), 2)

    def _draw_shutdown_button(self):
        r = self._shutdown_rect
        cx, cy = r.center
        rad = r.width // 2
        pygame.draw.circle(self.screen, theme.SHUTDOWN_DIM, (cx, cy), rad)
        pygame.draw.circle(self.screen, theme.SHUTDOWN, (cx, cy), rad, 3)
        # power symbol
        pygame.draw.circle(self.screen, theme.SHUTDOWN, (cx, cy), int(rad * 0.45), 2)
        pygame.draw.line(self.screen, theme.BACKGROUND,
                         (cx, cy - int(rad * 0.55)), (cx, cy + int(rad * 0.1)),
                         int(rad * 0.5))
        pygame.draw.line(self.screen, theme.SHUTDOWN,
                         (cx, cy - int(rad * 0.5)), (cx, cy), 3)

    def close(self):
        try:
            pygame.quit()
        except Exception:
            pass
