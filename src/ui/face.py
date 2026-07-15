"""
The robot's animated face (pygame) for the 7-inch Pi touchscreen.

The layout is chosen from the actual screen resolution, not just config:

Portrait (H > W, e.g. 480 × 800):
  ┌────────────────────┐  y = 0
  │  CAMERA PREVIEW    │  full-width live view + green face-detection boxes
  ├────────────────────┤  y ≈ 360
  │  [badge]  eyes     │  ROBOT FACE
  │           mouth    │
  ├────────────────────┤  y ≈ 592
  │  You / Robot text  │  CAPTIONS + shutdown button
  └────────────────────┘  y = 800

Landscape (W > H, e.g. 800 × 480):
  ┌──────────────────┬──────────────────────────────┐
  │  ROBOT FACE      │  CAMERA PREVIEW               │
  │  eyes + mouth    │  live view + face-detect box  │
  │  40% width       │  60% width                    │
  ├──────────────────┴──────────────────────────────┤
  │  You: "..."   Robot: "..."         [shutdown]    │
  └─────────────────────────────────────────────────┘

All drawing is best-effort; failures fall back gracefully without crashing.
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

        self.fps            = int(ui.get("fps", 30))
        self.show_captions  = bool(ui.get("show_captions", True))
        self._portrait_cfg  = bool(ui.get("portrait", False))   # user preference
        self.mirror_preview = bool(ui.get("mirror_preview", True))

        pygame.display.init()
        pygame.font.init()

        if ui.get("fullscreen", True):
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            # Non-fullscreen: request the size matching the config preference.
            self.screen = pygame.display.set_mode(
                (480, 800) if self._portrait_cfg else (800, 480))
        pygame.display.set_caption("Smart Campus Robot")
        try:
            pygame.mouse.set_visible(False)
        except Exception:
            pass

        self.W, self.H = self.screen.get_size()

        # ── Orientation + software-rotation logic ─────────────────────────────
        #
        # The Pi 7" touchscreen natively outputs 800×480 (landscape).
        # If /boot/firmware/config.txt has `display_rotate=1` (or 3), the OS
        # presents a 480×800 portrait framebuffer to software and physically
        # rotates the output 90°.  This makes every pixel on screen appear
        # rotated — eyes stack vertically, text appears sideways.
        #
        # Fix A (permanent, recommended): remove display_rotate from
        #         /boot/firmware/config.txt and reboot.
        # Fix B (software, applied below): render to an 800×480 canvas,
        #         rotate it 90° CCW, blit to the 480×800 framebuffer.
        #         The OS then rotates 90° CW → net rotation = 0. ✓
        #
        # `software_rotate` can be set manually in config.json ui section:
        #   0  = auto (default: no rotation, or 90 if screen appears portrait)
        #   90 = 90° CCW canvas rotation  (counteracts display_rotate=1)
        #  -90 = 90° CW  canvas rotation  (counteracts display_rotate=3)
        #  180 = 180°                      (counteracts display_rotate=2)
        # ─────────────────────────────────────────────────────────────────────

        self._sw_rotate   = int(ui.get("software_rotate", 0))
        self._real_screen = None   # set below if software rotation is active

        if self.W >= self.H:
            # Screen is landscape — landscape layout, no software rotation.
            self.portrait = False

        elif self._portrait_cfg:
            # Screen is portrait AND config wants portrait — portrait layout.
            self.portrait = True

        else:
            # Screen appears portrait (H > W) but config wants landscape.
            # This means display_rotate is active in the OS.  Apply software
            # rotation so the rendered landscape content appears correct.
            _scr_W, _scr_H = self.W, self.H        # e.g., 480 × 800
            self.W, self.H  = _scr_H, _scr_W        # swap to landscape: 800 × 480
            if self._sw_rotate == 0:
                self._sw_rotate = 90                 # 90° CCW counteracts 90° CW OS rotation
            self.portrait     = False
            self._real_screen = self.screen
            self.screen       = pygame.Surface((self.W, self.H))
            log.warning(
                "Screen is %dx%d (portrait) but portrait=False — "
                "software_rotate=%d active. "
                "If the display still looks rotated, try software_rotate=-90 in config. "
                "Permanent fix: remove display_rotate from /boot/firmware/config.txt.",
                _scr_W, _scr_H, self._sw_rotate,
            )

        self.clock = pygame.time.Clock()

        # ----- Layout rectangles ------------------------------------------
        if self.portrait:
            # Portrait 480×800: camera top, face middle, captions bottom.
            ph = int(self.H * float(ui.get("preview_height_frac", 0.45)))
            fh = int(self.H * float(ui.get("face_height_frac",    0.29)))
            ch = self.H - ph - fh
            self.preview_rect = pygame.Rect(0,       0,  self.W, ph)
            self.face_rect    = pygame.Rect(0,      ph,  self.W, fh)
            self.caption_rect = pygame.Rect(0, ph + fh,  self.W, ch)
        else:
            # Landscape 800×480: face left 40%, camera right 60%, captions bottom.
            # Camera column is ~480×340 — close to 4:3, matches the camera frame.
            cap_h  = int(self.H * 0.29) if self.show_captions else 0
            main_h = self.H - cap_h
            face_w = int(self.W * 0.40)
            cam_w  = self.W - face_w
            self.face_rect    = pygame.Rect(0,       0,      face_w, main_h)
            self.preview_rect = pygame.Rect(face_w,  0,      cam_w,  main_h)
            self.caption_rect = pygame.Rect(0,       main_h, self.W, cap_h)

        # ----- Fonts -------------------------------------------------------
        fh_ref = self.face_rect.height
        if self.portrait:
            self.font_status  = pygame.font.SysFont("Arial", max(16, int(fh_ref * theme.FONT_STATUS_FRAC)),  bold=True)
            self.font_caption = pygame.font.SysFont("Arial", max(14, int(fh_ref * theme.FONT_CAPTION_FRAC)))
            self.font_label   = pygame.font.SysFont("Arial", max(12, int(fh_ref * theme.FONT_LABEL_FRAC)),   bold=True)
            self.font_overlay = pygame.font.SysFont("Arial", max(14, int(fh_ref * 0.10)))
        else:
            # Landscape: caption bar is ~140px; scale text to fit it.
            cap_h_ref = max(40, self.caption_rect.height)
            self.font_status  = pygame.font.SysFont("Arial", max(16, int(fh_ref * 0.08)),       bold=True)
            self.font_caption = pygame.font.SysFont("Arial", max(14, int(cap_h_ref * 0.17)))
            self.font_label   = pygame.font.SysFont("Arial", max(12, int(cap_h_ref * 0.15)),    bold=True)
            self.font_overlay = pygame.font.SysFont("Arial", max(13, int(fh_ref * 0.056)))

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
            pygame.draw.rect(self.screen, theme.FACE_BG, self.face_rect)
            self._draw_face_landscape(sv, now)
            if self.preview_rect is not None:
                self._draw_camera_panel(sv)
            self._draw_notice(now)
            if self.show_captions:
                self._draw_captions_landscape()

        self._draw_shutdown_button()
        if self._real_screen is not None:
            # Software rotation: rotate the canvas then blit to the actual display.
            rotated = pygame.transform.rotate(self.screen, self._sw_rotate)
            self._real_screen.blit(rotated, (0, 0))
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
            if self.mirror_preview:
                scaled = pygame.transform.flip(scaled, True, False)
            self.screen.blit(scaled, r.topleft)
        except Exception:
            pygame.draw.rect(self.screen, theme.PANEL, r)
            pygame.draw.line(self.screen, theme.PANEL_BORDER,
                             r.bottomleft, r.bottomright, 1)
            return

        # Green face-detection boxes (x-coordinates mirrored to match the flipped preview)
        if self._frame_faces:
            fw, fh = self._frame_size
            sx = r.width  / fw
            sy = r.height / fh
            for (fx, fy, bw, bh) in self._frame_faces:
                if self.mirror_preview:
                    fx = fw - (fx + bw)   # mirror: left edge becomes right edge
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
        # Anchor to the preview / camera zone when available.
        r = self.preview_rect if self.preview_rect is not None else \
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
        """Landscape left column (40% of screen): animated face + status badge."""
        r  = self.face_rect
        cx = r.centerx

        color    = theme.eye_color(state_value)
        openness = self._eye_openness(now)
        bob_amp  = 0.0 if state_value in ("error",) else r.height * 0.016
        bob      = math.sin((now - self._t0) * 1.5) * bob_amp

        # Eyes: sized to fit comfortably inside the face column.
        # At 320×340: eye_rx≈38, eye_ry≈48, gap≈89 — fills column nicely.
        eye_y  = r.top + int(r.height * 0.48) + int(bob)
        eye_rx = int(r.width  * 0.12)
        eye_ry = int(r.height * 0.14)
        gap    = int(r.width  * 0.28)

        gox = int(self._gaze_x * eye_rx * 0.45)
        goy = int(self._gaze_y * eye_ry * 0.45)

        self._draw_eye(cx - gap, eye_y, eye_rx, eye_ry, color, openness, state_value, gox, goy)
        self._draw_eye(cx + gap, eye_y, eye_rx, eye_ry, color, openness, state_value, gox, goy)

        if state_value == "listening":
            self._draw_listening_ring(cx, eye_y, int(gap + eye_rx * 1.5), now)

        mouth_y = r.top + int(r.height * 0.74) + int(bob)
        self._draw_mouth(state_value, cx, mouth_y, eye_rx, int(r.height * 0.12), now)

        self._draw_status_badge(state_value)

    def _draw_captions_landscape(self):
        r   = self.caption_rect
        pad = int(self.W * 0.03)
        pygame.draw.rect(self.screen, theme.PANEL, r)
        pygame.draw.line(self.screen, theme.PANEL_BORDER, r.topleft, r.topright, 2)
        max_w = self.W - pad * 2
        y     = r.top + int(r.height * 0.08)
        if self._user_text:
            y = self._blit_labeled("You:", self._user_text, pad, y, max_w,
                                   theme.TEXT_SECONDARY, max_lines=1)
        if self._robot_text:
            self._blit_labeled("Robot:", self._robot_text, pad, y, max_w,
                               theme.TEXT_PRIMARY, max_lines=2)

    def _draw_camera_panel(self, state_value):
        """Landscape right column: live camera preview with face-detection boxes."""
        r = self.preview_rect
        pygame.draw.rect(self.screen, theme.PANEL, r)

        if self._preview is None:
            t = self.font_overlay.render("Camera not available", True, theme.PREVIEW_NONE)
            self.screen.blit(t, t.get_rect(center=r.center))
            pygame.draw.line(self.screen, theme.PANEL_BORDER, r.topleft, r.bottomleft, 2)
            return

        try:
            scaled = pygame.transform.smoothscale(self._preview, (r.width, r.height))
            if self.mirror_preview:
                scaled = pygame.transform.flip(scaled, True, False)
            self.screen.blit(scaled, r.topleft)
        except Exception:
            pygame.draw.rect(self.screen, theme.PANEL, r)
            pygame.draw.line(self.screen, theme.PANEL_BORDER, r.topleft, r.bottomleft, 2)
            return

        if self._frame_faces:
            fw, fh = self._frame_size
            sx = r.width / fw
            sy = r.height / fh
            for (fx, fy, bw, bh) in self._frame_faces:
                if self.mirror_preview:
                    fx = fw - (fx + bw)
                bx = r.x + int(fx * sx)
                by = r.y + int(fy * sy)
                try:
                    pygame.draw.rect(self.screen, theme.PREVIEW_BOX,
                                     (bx, by, int(bw * sx), int(bh * sy)), 2, border_radius=6)
                except TypeError:
                    pygame.draw.rect(self.screen, theme.PREVIEW_BOX,
                                     (bx, by, int(bw * sx), int(bh * sy)), 2)

        if not self._frame_faces and state_value == "idle":
            try:
                ov = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
                ov.fill((0, 0, 0, 70))
                self.screen.blit(ov, r.topleft)
            except Exception:
                pass
            t = self.font_overlay.render("Looking for you...", True, theme.PREVIEW_NONE)
            self.screen.blit(t, t.get_rect(center=r.center))

        # Left border dividing face column from camera column
        pygame.draw.line(self.screen, theme.PANEL_BORDER, r.topleft, r.bottomleft, 2)

    def _draw_preview_thumbnail(self):
        tw = int(self.W * 0.16)
        th = int(tw * 0.75)
        try:
            thumb = pygame.transform.smoothscale(self._preview, (tw, th))
            if self.mirror_preview:
                thumb = pygame.transform.flip(thumb, True, False)
        except Exception:
            return
        x = self.W - tw - int(self.W * 0.02)
        y = int(self.H * 0.03)
        self.screen.blit(thumb, (x, y))
        pygame.draw.rect(self.screen, theme.PANEL_BORDER, (x, y, tw, th), 2)
        # Face boxes on thumbnail (x-mirrored when mirror_preview is on)
        if self._frame_faces:
            fw, fh = self._frame_size
            sx, sy = tw / fw, th / fh
            for (fx, fy, bw, bh) in self._frame_faces:
                if self.mirror_preview:
                    fx = fw - (fx + bw)
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
        bx = self.face_rect.x + (self.face_rect.width - badge_w) // 2
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
