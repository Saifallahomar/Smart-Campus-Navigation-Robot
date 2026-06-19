"""
The robot's animated face (pygame) — portrait layout for the 7-inch Pi screen.

Portrait layout (480 × 800):
  ┌────────────────────┐  y = 0
  │                    │
  │  CAMERA PREVIEW    │  full-width live view with green face boxes
  │  480 × ~360 px     │  "Looking for you..." when no face detected
  │                    │
  ├────────────────────┤  y ≈ 360  (config: ui.preview_height_frac)
  │  [status badge]    │
  │  👀  eyes  👀     │  ROBOT FACE  — emotions change with state
  │      mouth         │
  ├────────────────────┤  y ≈ 592  (config: ui.face_height_frac)
  │  You:  "..."       │  CAPTIONS
  │  Robot: "..."      │
  │               [🔴] │  safe-shutdown button
  └────────────────────┘  y = 800

Landscape fallback (ui.portrait = false):
  Full-screen face with a small camera thumbnail in the corner —
  same behaviour as before this change.

All drawing is best-effort; if a feature fails it falls back gracefully
rather than crashing the robot.
"""

import math
import random
import time

import pygame

try:
    import pygame.gfxdraw as gfxdraw
    _HAS_GFX = True
except Exception:
    _HAS_GFX = False

from src.ui import theme
from src.utils.logging_setup import get_logger

log = get_logger("face")


class Face:
    def __init__(self, settings):
        self.settings = settings
        ui = settings.ui

        self.fps           = int(ui.get("fps", 30))
        self.show_captions = bool(ui.get("show_captions", True))
        self.portrait      = bool(ui.get("portrait", False))

        pygame.display.init()
        pygame.font.init()

        if ui.get("fullscreen", True):
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode((480, 800) if self.portrait else (800, 480))
        pygame.display.set_caption("Smart Campus Robot")
        try:
            pygame.mouse.set_visible(False)
        except Exception:
            pass

        self.W, self.H = self.screen.get_size()
        self.clock = pygame.time.Clock()

        # ----- Layout rectangles ------------------------------------------
        if self.portrait:
            ph = int(self.H * float(ui.get("preview_height_frac", 0.45)))
            fh = int(self.H * float(ui.get("face_height_frac",    0.29)))
            ch = self.H - ph - fh
            self.preview_rect = pygame.Rect(0,       0,  self.W, ph)
            self.face_rect    = pygame.Rect(0,      ph,  self.W, fh)
            self.caption_rect = pygame.Rect(0, ph + fh,  self.W, ch)
        else:
            # Landscape: full screen for the face, captions at the bottom.
            ch = int(self.H * 0.26) if self.show_captions else 0
            self.preview_rect = None   # just a small thumbnail overlay
            self.face_rect    = pygame.Rect(0, 0,       self.W, self.H - ch)
            self.caption_rect = pygame.Rect(0, self.H - ch, self.W, ch)

        # ----- Fonts (scaled to the face zone, not the full screen) ---------
        fh_ref = self.face_rect.height
        self.font_status  = pygame.font.SysFont("Arial", max(16, int(fh_ref * theme.FONT_STATUS_FRAC)),  bold=True)
        self.font_caption = pygame.font.SysFont("Arial", max(14, int(fh_ref * theme.FONT_CAPTION_FRAC)))
        self.font_label   = pygame.font.SysFont("Arial", max(12, int(fh_ref * theme.FONT_LABEL_FRAC)),   bold=True)
        self.font_overlay = pygame.font.SysFont("Arial", max(14, int(fh_ref * 0.10)))

        # ----- Shutdown button (bottom-right of caption area) ---------------
        btn    = int(self.W * 0.12)
        margin = int(btn * 0.35)
        self._shutdown_rect = pygame.Rect(
            self.W - btn - margin,
            self.H - btn - margin,
            btn, btn)

        # ----- Animation state ----------------------------------------------
        self._t0              = time.time()
        self._next_blink      = time.time() + random.uniform(2, 5)
        self._blinking_until  = 0.0

        # ----- Eye gaze (where the pupils look) -----------------------------
        # Target is set from the camera (person position); the drawn value
        # eases toward it so the eyes glide smoothly instead of snapping.
        self._gaze_tx = 0.0   # target  -1 (left) .. +1 (right)
        self._gaze_ty = 0.0   # target  -1 (up)   .. +1 (down)
        self._gaze_x  = 0.0   # current (smoothed)
        self._gaze_y  = 0.0

        # ----- Transient on-screen notice (e.g. "User is waving") -----------
        self._notice       = ""
        self._notice_until = 0.0

        # ----- Camera preview state -----------------------------------------
        self._preview     = None    # latest pygame Surface from camera
        self._frame_faces = []      # latest face boxes [(x,y,w,h) ...]
        self._frame_size  = (640, 480)

        # ----- Captions / status text ---------------------------------------
        self._user_text  = ""
        self._robot_text = ""
        self._status     = ""

        log.info("Face ready (%d×%d, portrait=%s, gfx=%s).",
                 self.W, self.H, self.portrait, _HAS_GFX)

    # ---------------------------------------------------------------- setters
    def set_caption(self, user=None, robot=None):
        if user  is not None: self._user_text  = user
        if robot is not None: self._robot_text = robot

    def clear_caption(self):
        self._user_text  = ""
        self._robot_text = ""

    def set_status(self, text):
        self._status = text or ""

    def set_gaze(self, dx, dy=0.0):
        """
        Point the eyes toward a person. dx/dy are -1..+1 offsets from the centre
        of the camera frame (negative = left/up). Screen eyes only — this never
        moves the physical head.
        """
        self._gaze_tx = max(-1.0, min(1.0, float(dx)))
        self._gaze_ty = max(-1.0, min(1.0, float(dy)))

    def set_notice(self, text, seconds=2.5):
        """Show a short banner over the camera preview for a few seconds."""
        self._notice       = text or ""
        self._notice_until = time.time() + seconds

    def set_preview(self, frame_rgb, faces=None, frame_size=(640, 480)):
        """
        Store the latest camera frame for display.

        Args:
            frame_rgb:  numpy HxWx3 RGB array, or None.
            faces:      list of (x, y, w, h) boxes in frame coordinates.
            frame_size: (width, height) of the source frame.
        """
        self._frame_faces = faces or []
        self._frame_size  = frame_size or (640, 480)
        if frame_rgb is None:
            self._preview = None
            return
        try:
            import numpy as np
            surf = pygame.surfarray.make_surface(np.swapaxes(frame_rgb, 0, 1))
            self._preview = surf.convert()   # convert once for faster blitting
        except Exception:
            self._preview = None

    # --------------------------------------------------------------- events
    def pump_events(self):
        """Return high-level event strings: 'quit' or 'shutdown'."""
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

    # --------------------------------------------------------------- render
    def render(self, state, mouth_open=False):
        """Draw one frame. Called as fast as fps allows."""
        now = time.time()
        sv  = state.value if hasattr(state, "value") else str(state)

        # Ease the eye gaze toward its target so the look is smooth, not jumpy.
        self._gaze_x += (self._gaze_tx - self._gaze_x) * 0.18
        self._gaze_y += (self._gaze_ty - self._gaze_y) * 0.18

        self.screen.fill(theme.BACKGROUND)

        if self.portrait:
            self._draw_preview_zone(sv)
            self._draw_notice(now)
            self._draw_face_zone(sv, now)
            if self.show_captions:
                self._draw_caption_zone()
        else:
            self._draw_face_landscape(sv, now)
            if self.show_captions:
                self._draw_captions_landscape()
            if self._preview is not None:
                self._draw_preview_thumbnail()
            self._draw_notice(now)

        self._draw_shutdown_button()
        pygame.display.flip()
        self.clock.tick(self.fps)

    # ========================================================= PORTRAIT ZONES

    def _draw_preview_zone(self, state_value):
        """Top zone: full-width live camera view with face detection boxes."""
        r = self.preview_rect

        if self._preview is None:
            # No camera - dark placeholder
            pygame.draw.rect(self.screen, theme.PANEL, r)
            t = self.font_overlay.render("Camera not available", True, theme.PREVIEW_NONE)
            self.screen.blit(t, t.get_rect(center=r.center))
            pygame.draw.line(self.screen, theme.PANEL_BORDER,
                             r.bottomleft, r.bottomright, 1)
            return

        # Scale the camera frame to fill the preview zone
        try:
            scaled = pygame.transform.smoothscale(self._preview, (r.width, r.height))
            self.screen.blit(scaled, r.topleft)
        except Exception:
            pygame.draw.rect(self.screen, theme.PANEL, r)
            pygame.draw.line(self.screen, theme.PANEL_BORDER,
                             r.bottomleft, r.bottomright, 1)
            return

        # Green face-detection boxes
        if self._frame_faces:
            fw, fh = self._frame_size
            sx = r.width  / fw
            sy = r.height / fh
            for (fx, fy, bw, bh) in self._frame_faces:
                bx = r.x + int(fx * sx)
                by = r.y + int(fy * sy)
                try:
                    pygame.draw.rect(self.screen, theme.PREVIEW_BOX,
                                     (bx, by, int(bw * sx), int(bh * sy)),
                                     2, border_radius=6)
                except TypeError:
                    # pygame < 2.0 doesn't support border_radius
                    pygame.draw.rect(self.screen, theme.PREVIEW_BOX,
                                     (bx, by, int(bw * sx), int(bh * sy)), 2)

        # "Looking for you..." overlay when no face is in frame
        if not self._frame_faces and state_value == "idle":
            try:
                ov = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
                ov.fill((0, 0, 0, 70))
                self.screen.blit(ov, r.topleft)
            except Exception:
                pass
            t = self.font_overlay.render("Looking for you...", True, theme.PREVIEW_NONE)
            self.screen.blit(t, t.get_rect(center=r.center))

        # Thin border line separating camera from face zone
        pygame.draw.line(self.screen, theme.PANEL_BORDER,
                         r.bottomleft, r.bottomright, 1)

    def _draw_notice(self, now):
        """Transient banner near the top of the preview, e.g. 'User is waving'."""
        if not self._notice or now >= self._notice_until:
            return
        # Anchor to the preview zone in portrait, or the top of the screen otherwise.
        r = self.preview_rect if (self.portrait and self.preview_rect) else \
            pygame.Rect(0, 0, self.W, int(self.H * 0.12))
        surf = self.font_overlay.render(self._notice, True, theme.NOTICE_TEXT)
        sw, sh = surf.get_size()
        px, py = int(sw * 0.18), int(sh * 0.35)
        bw, bh = sw + px * 2, sh + py * 2
        bx = r.x + (r.width - bw) // 2
        by = r.y + int(r.height * 0.06)
        try:
            badge = pygame.Surface((bw, bh), pygame.SRCALPHA)
            pygame.draw.rect(badge, (*theme.NOTICE_BG, 235), (0, 0, bw, bh),
                             border_radius=bh // 2)
            self.screen.blit(badge, (bx, by))
        except Exception:
            pygame.draw.rect(self.screen, theme.NOTICE_BG, (bx, by, bw, bh))
        self.screen.blit(surf, (bx + px, by + py))

    def _draw_face_zone(self, state_value, now):
        """Middle zone: the animated robot face + status badge."""
        r = self.face_rect

        # Subtle face background
        pygame.draw.rect(self.screen, theme.FACE_BG, r)

        # Status badge at the top of this zone
        self._draw_status_badge(state_value)

        color    = theme.eye_color(state_value)
        openness = self._eye_openness(now)
        # Gentle idle bob (slows during error, stops when speaking)
        bob_amp = 0.0 if state_value in ("error",) else r.height * 0.022
        bob     = math.sin((now - self._t0) * 1.5) * bob_amp

        # Eye geometry relative to face_rect
        cx    = r.centerx
        # Eye centre sits at ~55% down the face zone
        eye_y = r.top + int(r.height * 0.52) + int(bob)
        eye_rx = int(self.W * 0.105)
        eye_ry = int(r.height * 0.20)
        gap    = int(self.W * 0.185)     # half-distance between eye centres

        gox = int(self._gaze_x * eye_rx * 0.42)   # pupil shift left/right
        goy = int(self._gaze_y * eye_ry * 0.42)   # pupil shift up/down

        self._draw_eye(cx - gap, eye_y, eye_rx, eye_ry, color, openness, state_value, gox, goy)
        self._draw_eye(cx + gap, eye_y, eye_rx, eye_ry, color, openness, state_value, gox, goy)

        # Listening pulse ring
        if state_value == "listening":
            self._draw_listening_ring(cx, eye_y, int(gap + eye_rx * 1.4), now)

        # Mouth
        mouth_y = r.top + int(r.height * 0.80) + int(bob)
        self._draw_mouth(state_value, cx, mouth_y, eye_rx, int(r.height * 0.18), now)

    def _draw_caption_zone(self):
        """Bottom zone: You / Robot text and status label."""
        r = self.caption_rect

        pygame.draw.rect(self.screen, theme.PANEL, r)
        pygame.draw.line(self.screen, theme.PANEL_BORDER,
                         r.topleft, r.topright, 1)

        pad   = int(self.W * 0.05)
        max_w = self.W - pad * 2
        y     = r.top + int(r.height * 0.10)

        if self._user_text:
            y = self._blit_labeled("You:", self._user_text, pad, y, max_w,
                                   theme.TEXT_SECONDARY, max_lines=1)
        if self._robot_text:
            self._blit_labeled("Robot:", self._robot_text, pad, y, max_w,
                               theme.TEXT_PRIMARY, max_lines=2)

    # ====================================================== LANDSCAPE FALLBACK

    def _draw_face_landscape(self, state_value, now):
        """Original landscape layout: face fills the screen (minus caption bar)."""
        r  = self.face_rect
        cx = r.centerx

        color    = theme.eye_color(state_value)
        openness = self._eye_openness(now)
        bob      = math.sin((now - self._t0) * 1.5) * (r.height * 0.006)

        eye_y  = r.top + int(r.height * 0.42) + int(bob)
        eye_rx = int(self.W * 0.085)
        eye_ry = int(r.height * 0.12)
        gap    = int(self.W * 0.20)

        gox = int(self._gaze_x * eye_rx * 0.42)
        goy = int(self._gaze_y * eye_ry * 0.42)

        self._draw_eye(cx - gap, eye_y, eye_rx, eye_ry, color, openness, state_value, gox, goy)
        self._draw_eye(cx + gap, eye_y, eye_rx, eye_ry, color, openness, state_value, gox, goy)

        mouth_y = r.top + int(r.height * 0.66) + int(bob)
        self._draw_mouth(state_value, cx, mouth_y, eye_rx, int(r.height * 0.12), now)

        if self._status:
            s = self.font_status.render(self._status, True, theme.STATUS_TEXT)
            self.screen.blit(s, s.get_rect(center=(cx, r.top + int(r.height * 0.10))))

    def _draw_captions_landscape(self):
        r   = self.caption_rect
        pad = int(self.W * 0.04)
        pygame.draw.rect(self.screen, theme.PANEL, r)
        pygame.draw.line(self.screen, theme.PANEL_BORDER, r.topleft, r.topright, 2)
        max_w = self.W - pad * 2
        y     = r.top + int(r.height * 0.10)
        if self._user_text:
            y = self._blit_labeled("You:", self._user_text, pad, y, max_w,
                                   theme.TEXT_SECONDARY, max_lines=1)
        if self._robot_text:
            self._blit_labeled("Robot:", self._robot_text, pad, y, max_w,
                               theme.TEXT_PRIMARY, max_lines=2)

    def _draw_preview_thumbnail(self):
        tw = int(self.W * 0.16)
        th = int(tw * 0.75)
        try:
            thumb = pygame.transform.smoothscale(self._preview, (tw, th))
        except Exception:
            return
        x = self.W - tw - int(self.W * 0.02)
        y = int(self.H * 0.03)
        self.screen.blit(thumb, (x, y))
        pygame.draw.rect(self.screen, theme.PANEL_BORDER, (x, y, tw, th), 2)
        # Face boxes on thumbnail
        if self._frame_faces:
            fw, fh = self._frame_size
            sx, sy = tw / fw, th / fh
            for (fx, fy, bw, bh) in self._frame_faces:
                pygame.draw.rect(self.screen, theme.PREVIEW_BOX,
                                 (x + int(fx*sx), y + int(fy*sy),
                                  int(bw*sx), int(bh*sy)), 1)

    # ============================================================= DRAWING BITS

    def _eye_openness(self, now):
        """Return 0.0 (closed) .. 1.0 (open) — produces a natural blink."""
        if self._blinking_until == 0.0 and now >= self._next_blink:
            self._blinking_until = now + 0.18
        if self._blinking_until:
            remaining = self._blinking_until - now
            if remaining <= 0:
                self._blinking_until = 0.0
                self._next_blink = now + random.uniform(2.5, 6.0)
                return 1.0
            total   = 0.18
            elapsed = total - remaining
            half    = total / 2
            return 1.0 - (elapsed / half) if elapsed < half else (elapsed - half) / half
        return 1.0

    def _draw_eye(self, cx, cy, rx, ry, color, openness, state_value, gx=0, gy=0):
        cx, cy, rx = int(cx), int(cy), int(rx)

        # ERROR state: X-shaped eyes
        if state_value == "error":
            s = int(rx * 0.75)
            w = max(4, int(ry * 0.30))
            pygame.draw.line(self.screen, color, (cx-s, cy-s//2), (cx+s, cy+s//2), w)
            pygame.draw.line(self.screen, color, (cx+s, cy-s//2), (cx-s, cy+s//2), w)
            return

        # Closed eye = soft horizontal line
        if openness < 0.12:
            pygame.draw.line(self.screen, color,
                             (cx - rx, cy), (cx + rx, cy),
                             max(4, int(ry * 0.25)))
            return

        # HAPPY: squinted, cute upward arc (no pupil) ^_^
        if state_value == "happy":
            arc_ry = max(6, int(ry * 0.85))
            rect = pygame.Rect(cx - rx, cy - arc_ry, rx * 2, arc_ry * 2)
            pygame.draw.arc(self.screen, color, rect, 0.30, 2.84, max(5, int(ry * 0.30)))
            return

        # Normal open eye — big rounded eye with a pupil that follows the person.
        ry_eff = max(3, int(ry * openness))
        if _HAS_GFX:
            gfxdraw.filled_ellipse(self.screen, cx, cy, rx, ry_eff, color)
            gfxdraw.aaellipse(   self.screen, cx, cy, rx, ry_eff, color)
        else:
            pygame.draw.ellipse(self.screen, color,
                                (cx - rx, cy - ry_eff, rx * 2, ry_eff * 2))

        # Pupil — dark circle offset by the gaze, clamped to stay inside the eye.
        pr = max(3, int(rx * 0.46))
        max_ox = max(0, rx - pr - int(rx * 0.10))
        max_oy = max(0, ry_eff - pr - int(ry_eff * 0.10))
        px = cx + max(-max_ox, min(max_ox, int(gx)))
        py = cy + max(-max_oy, min(max_oy, int(gy)))
        # When the eye is mid-blink the pupil would overflow — shrink it to fit.
        pr = min(pr, max(2, ry_eff - 1))
        if _HAS_GFX:
            gfxdraw.filled_circle(self.screen, px, py, pr, theme.PUPIL)
            gfxdraw.aacircle(    self.screen, px, py, pr, theme.PUPIL)
        else:
            pygame.draw.circle(self.screen, theme.PUPIL, (px, py), pr)

        # Bright glint on the pupil for a lively, cute look.
        gr = max(2, int(pr * 0.42))
        gxx = px - int(pr * 0.32)
        gyy = py - int(pr * 0.34)
        if _HAS_GFX:
            gfxdraw.filled_circle(self.screen, gxx, gyy, gr, theme.HIGHLIGHT)
            gfxdraw.aacircle(    self.screen, gxx, gyy, gr, theme.HIGHLIGHT)
        else:
            pygame.draw.circle(self.screen, theme.HIGHLIGHT, (gxx, gyy), gr)

    def _draw_mouth(self, state_value, cx, my, rx, ry, now):
        cx, my = int(cx), int(my)
        color  = theme.MOUTH
        mw = int(rx * 1.1)
        mh = int(ry * 0.55)

        if state_value == "speaking":
            # Fluid open/close driven by time (ignores the bool; looks smoother)
            wave     = abs(math.sin(now * 7.0))
            open_rx  = int(mw * (0.35 + 0.55 * wave))
            open_ry  = int(mh * (0.40 + 0.60 * wave))
            if _HAS_GFX:
                gfxdraw.filled_ellipse(self.screen, cx, my, open_rx, open_ry, color)
                gfxdraw.aaellipse(    self.screen, cx, my, open_rx, open_ry, color)
            else:
                pygame.draw.ellipse(self.screen, color,
                                    (cx - open_rx, my - open_ry,
                                     open_rx * 2,  open_ry * 2))

        elif state_value == "thinking":
            # Three animated bouncing dots
            dot_r   = max(5, int(mw * 0.18))
            spacing = dot_r * 3.2
            for i, ox in enumerate((-spacing, 0, spacing)):
                dy  = math.sin(now * 4.5 + i * 1.1) * dot_r * 1.4
                dcx = int(cx + ox)
                dcy = int(my + dy)
                if _HAS_GFX:
                    gfxdraw.filled_circle(self.screen, dcx, dcy, dot_r, color)
                    gfxdraw.aacircle(    self.screen, dcx, dcy, dot_r, color)
                else:
                    pygame.draw.circle(self.screen, color, (dcx, dcy), dot_r)

        elif state_value == "confused":
            # Tilted / uncertain line
            thickness = max(5, int(mh * 0.32))
            pygame.draw.line(self.screen, color,
                             (cx - int(mw * 0.6), my + int(mh * 0.1)),
                             (cx + int(mw * 0.6), my - int(mh * 0.3)),
                             thickness)

        elif state_value == "listening":
            # Neutral flat line — attentive
            thickness = max(5, int(mh * 0.32))
            pygame.draw.line(self.screen, color,
                             (cx - int(mw * 0.45), my),
                             (cx + int(mw * 0.45), my),
                             thickness)

        elif state_value == "error":
            # Slight frown
            rect = pygame.Rect(cx - mw, my, mw * 2, mh * 2)
            pygame.draw.arc(self.screen, color, rect, 0.3, 2.85,
                            max(5, int(mh * 0.32)))

        else:
            # idle / happy / face_detected → friendly smile
            smile_scale = 1.15 if state_value == "happy" else 1.0
            rect = pygame.Rect(cx - int(mw * smile_scale),
                               my - int(mh * smile_scale),
                               int(mw * 2 * smile_scale),
                               int(mh * 2 * smile_scale))
            pygame.draw.arc(self.screen, color, rect, 3.4, 6.0,
                            max(5, int(mh * 0.32)))

    def _draw_listening_ring(self, cx, cy, radius, now):
        """Subtle pulsing ring around the face while listening."""
        pulse = 0.92 + 0.08 * math.sin(now * 3.0)
        r     = int(radius * pulse)
        col   = theme.EYE_COLORS["listening"]
        if _HAS_GFX:
            gfxdraw.aacircle(self.screen, int(cx), int(cy), r, col)
        else:
            pygame.draw.circle(self.screen, col, (int(cx), int(cy)), r, 2)

    def _draw_status_badge(self, state_value):
        """Coloured pill-shaped label at the top of the face zone."""
        text  = self._status
        color = theme.badge_color(state_value)
        if not text or color is None:
            return

        surf = self.font_status.render(text, True, theme.STATUS_TEXT)
        sw, sh = surf.get_size()
        px, py = int(sw * 0.40), int(sh * 0.28)
        badge_w = sw + px * 2
        badge_h = sh + py * 2
        bx = (self.W - badge_w) // 2
        by = self.face_rect.top + int(self.face_rect.height * 0.04)

        try:
            pygame.draw.rect(self.screen, color,
                             (bx, by, badge_w, badge_h),
                             border_radius=badge_h // 2)
        except TypeError:
            pygame.draw.rect(self.screen, color, (bx, by, badge_w, badge_h))

        self.screen.blit(surf, (bx + px, by + py))

    def _draw_shutdown_button(self):
        r  = self._shutdown_rect
        cx, cy = r.center
        rad    = r.width // 2
        pygame.draw.circle(self.screen, theme.SHUTDOWN_DIM, (cx, cy), rad)
        pygame.draw.circle(self.screen, theme.SHUTDOWN,     (cx, cy), rad, 3)
        # Power symbol
        pygame.draw.circle(self.screen, theme.SHUTDOWN,     (cx, cy), int(rad * 0.44), 2)
        pygame.draw.line(  self.screen, theme.FACE_BG,
                           (cx, cy - int(rad * 0.55)), (cx, cy + int(rad * 0.08)),
                           max(4, int(rad * 0.45)))
        pygame.draw.line(  self.screen, theme.SHUTDOWN,
                           (cx, cy - int(rad * 0.50)), (cx, cy), 3)

    # ---------------------------------------------- caption helpers (shared)
    def _blit_labeled(self, label, text, x, y, max_w, color, max_lines=2):
        lbl = self.font_label.render(label, True, color)
        self.screen.blit(lbl, (x, y))
        lines = self._wrap(text, self.font_caption, max_w)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip() + "..."
        ty = y + lbl.get_height() + 3
        for ln in lines:
            s = self.font_caption.render(ln, True, color)
            self.screen.blit(s, (x, ty))
            ty += s.get_height() + 2
        return ty + int(self.face_rect.height * 0.02)

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
        return lines or [""]

    # --------------------------------------------------------------- cleanup
    def close(self):
        try:
            pygame.quit()
        except Exception:
            pass
