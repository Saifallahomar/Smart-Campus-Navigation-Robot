"""
Servo head — drives ONE real pan servo so the head follows a person's face.

This is a drop-in subclass of HeadController. The rest of the robot is unchanged:
src/vision/tracker.py produces a smoothed (dx, dy) offset, src/core/robot.py calls
self.head.aim(dx, dy), and that updates the pan *target*. The difference here is
that _apply() now drives a physical servo on a GPIO pin.

How it stays smooth and professional (not twitchy like a basic hobby build):

  * Decoupled control loop. A background thread runs at a steady ~50 Hz and eases
    the servo toward the latest target. The camera only updates the target a few
    times a second (and in bursts), but the motion stays smooth because the servo
    loop interpolates between updates.
  * Speed limit. The head can only move so many degrees per second, so it glides
    instead of snapping.
  * Deadzone. Tiny offsets near the centre are ignored, so it doesn't hunt or
    jitter when the person is already centred.
  * Idle detach (anti-buzz). Once the head has settled, it stops sending PWM
    pulses so the servo goes quiet instead of humming and twitching. It re-engages
    the instant a new movement is needed. This also reduces wear on the servo.

Wiring (single servo, e.g. SG90 / MG996R):
    Signal (orange/yellow) -> GPIO 18  (physical pin 12)
    Power  (red)           -> 5V       (physical pin 2 or 4)
    Ground (brown/black)   -> GND      (physical pin 6)
  For a high-torque servo (MG996R), power it from a separate 5V supply, not the
  Pi's 5V pin, and share the ground with the Pi.

If gpiozero (or a working pin backend) is not available — e.g. on a Windows
development machine — this falls back to the no-op base controller so the program
still runs everywhere.
"""

import threading
import time

from src.hardware.head_controller import HeadController
from src.utils.logging_setup import get_logger

log = get_logger("servo_head")

# gpiozero is only present on the Pi. Import lazily so dev machines still run.
try:
    from gpiozero import AngularServo
    _GPIOZERO_OK = True
except Exception as _exc:  # ImportError, or no pin factory available
    AngularServo = None
    _GPIOZERO_OK = False
    log.debug("gpiozero not available (%s) — servo head will stay in no-op mode.", _exc)


class ServoHead(HeadController):
    """HeadController that drives one real pan servo, smoothly."""

    def __init__(self, settings=None, step=0.5):
        super().__init__(settings, step=step)

        cfg = {}
        if settings is not None:
            cfg = settings.get("servo") or {}

        self.gpio_pin   = int(cfg.get("gpio_pin", 18))
        self.min_angle  = float(cfg.get("min_angle", -90.0))
        self.max_angle  = float(cfg.get("max_angle", 90.0))
        self.center_ang = float(cfg.get("center_angle", 0.0))
        self.max_speed  = float(cfg.get("max_speed_deg_per_sec", 90.0))
        # Fraction of the remaining distance covered each tick (ease-out). Lower
        # = smoother and gentler; higher = snappier.
        self.smoothing  = float(cfg.get("smoothing", 0.18))
        # deadzone: how close counts as "arrived" (then it stops).
        # wake_zone: how big a change must be to start moving again. wake_zone
        # being larger than deadzone gives hysteresis, so small camera wobble
        # doesn't make the servo twitch.
        self.deadzone   = float(cfg.get("deadzone_deg", 2.0))
        self.wake_zone  = float(cfg.get("wake_zone_deg", 5.0))
        self.invert     = bool(cfg.get("invert", False))
        self.idle_release = float(cfg.get("idle_release_seconds", 1.5))
        # Pulse widths in seconds. SG90 full range is roughly 0.5ms..2.5ms.
        min_pulse = float(cfg.get("min_pulse_width_ms", 0.5)) / 1000.0
        max_pulse = float(cfg.get("max_pulse_width_ms", 2.5)) / 1000.0

        self._servo = None
        self._cur_angle = self.center_ang   # where the servo physically is
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_move = time.time()
        self._detached = False
        self._moving = False

        if not _GPIOZERO_OK:
            log.warning("Servo requested but gpiozero is unavailable; "
                        "head tracking will be simulated only.")
            return

        try:
            self._servo = AngularServo(
                self.gpio_pin,
                min_angle=self.min_angle,
                max_angle=self.max_angle,
                min_pulse_width=min_pulse,
                max_pulse_width=max_pulse,
                initial_angle=self.center_ang,
            )
            self.connected = True
            log.info("Servo head ready on GPIO %d (range %.0f..%.0f deg).",
                     self.gpio_pin, self.min_angle, self.max_angle)
        except Exception as exc:
            # Pin busy, no backend, wrong board — don't crash the robot.
            self._servo = None
            log.warning("Could not start servo on GPIO %d (%s); "
                        "falling back to no-op head.", self.gpio_pin, exc)
            return

        # Steady control loop, independent of the (bursty) camera frame rate.
        self._thread = threading.Thread(
            target=self._control_loop, name="servo-head", daemon=True)
        self._thread.start()

    # --------------------------------------------------------------- targeting

    def _apply(self, pan, tilt):
        """
        Called by the base aim()/center() with the desired pan (-1..+1).
        We only record the target; the control loop does the smooth movement.
        Tilt is ignored — this is a single (pan) servo build.
        """
        if not self.connected:
            return super()._apply(pan, tilt)  # keep the helpful debug log
        # self.pan is already updated by the base class; nothing else to do.
        # Waking the loop happens naturally on the next tick.

    def _target_angle(self):
        """Map the normalized pan target (-1..+1) to a real servo angle."""
        pan = max(-1.0, min(1.0, self.pan))
        if self.invert:
            pan = -pan
        # -1 -> min_angle, +1 -> max_angle
        span = (self.max_angle - self.min_angle) / 2.0
        mid = (self.max_angle + self.min_angle) / 2.0
        return mid + pan * span

    # ------------------------------------------------------------- control loop

    def _control_loop(self):
        dt = 0.02  # 50 Hz
        while not self._stop.is_set():
            target = self._target_angle()
            diff = target - self._cur_angle
            adiff = abs(diff)

            # Hysteresis: start moving only for a clearly real change, and keep
            # moving until comfortably settled. This stops tiny camera wobble
            # from making the servo shake.
            if self._moving:
                if adiff <= self.deadzone:
                    self._moving = False
            elif adiff >= self.wake_zone:
                self._moving = True

            if not self._moving:
                # Resting. After a quiet spell, stop pulsing so the servo goes
                # silent (no buzz) and takes a break.
                if (not self._detached
                        and time.time() - self._last_move > self.idle_release):
                    self._detach()
                self._stop.wait(dt)
                continue

            # Moving: ease-out toward the target (covers a fraction of the
            # remaining distance each tick, so it decelerates as it arrives),
            # capped to a max speed so it always glides smoothly.
            self._detached = False
            self._last_move = time.time()
            step = diff * self.smoothing
            max_step = self.max_speed * dt
            if step > max_step:
                step = max_step
            elif step < -max_step:
                step = -max_step
            self._cur_angle += step
            self._write(self._cur_angle)
            self._stop.wait(dt)

    def _write(self, angle):
        angle = max(self.min_angle, min(self.max_angle, angle))
        try:
            with self._lock:
                if self._servo is not None:
                    self._servo.angle = angle
        except Exception as exc:
            log.debug("Servo write failed: %s", exc)

    def _detach(self):
        try:
            with self._lock:
                if self._servo is not None:
                    self._servo.detach()  # stop PWM -> servo goes quiet
            self._detached = True
            log.debug("Servo idle — pulses off.")
        except Exception as exc:
            log.debug("Servo detach failed: %s", exc)

    # --------------------------------------------------------------- shutdown

    def close(self):
        """Stop the loop, recentre, and release the servo cleanly."""
        self._stop.set()
        try:
            if self._servo is not None:
                with self._lock:
                    self._servo.angle = self.center_ang
                time.sleep(0.3)  # let it reach centre before releasing
                with self._lock:
                    self._servo.detach()
                    self._servo.close()
        except Exception as exc:
            log.debug("Servo close error: %s", exc)
        log.info("Servo head released.")
