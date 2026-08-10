"""
Serial link to the Arduino Mega motor controller.

Connects to /dev/ttyACM0 at 9600 baud (configurable in config.json under
the 'arduino' key).  A background reader thread handles incoming messages so
the main robot loop is never blocked.

Commands sent TO the Arduino:
  MOVEF:1   move forward 1 metre
  MOVEB:1   move backward 1 metre
  TOUR      start the 35-metre campus tour
  ARM_RUN   run arm + vacuum + blocker
  ARM_HOME  home the arm back
  STOP      stop everything
  F B L R S directional / remote-control buttons

Replies FROM the Arduino:
  READY
  STATE:MOVING
  DONE:MOVEF / DONE:MOVEB / DONE:TOUR / DONE:ARM_RUN
  OBSTACLE:PLEASE_CLEAR_THE_WAY
  STATE:PATH_CLEAR_RESUMING
  ERROR:ROBOT_MOVING_ARM_BLOCKED

If the serial port is not found (e.g. on a dev laptop), the controller runs
in mock mode — every command is just logged. The robot still starts normally.
"""

import threading
import time

from src.utils.logging_setup import get_logger

log = get_logger("arduino")

try:
    import serial as pyserial
    _HAS_SERIAL = True
except ImportError:
    _HAS_SERIAL = False


class ArduinoController:
    """
    Manages the serial connection to the Arduino Mega.

    Quick-start example in robot.py::

        self.arduino = ArduinoController(settings)
        self.arduino.on_obstacle = self._on_obstacle

        self.arduino.move_forward()        # send MOVEF:1
        self.arduino.run_arm()             # send ARM_RUN
        while self.arduino.is_moving: ...  # wait for DONE
    """

    def __init__(self, settings):
        cfg = settings.get("arduino") or {}
        self.port          = cfg.get("port",          "/dev/ttyACM0")
        self.baud          = int(cfg.get("baud",       9600))
        self.tour_password = cfg.get("tour_password",  "1234")

        self._serial = None
        self._lock   = threading.Lock()

        # State flags — updated by the reader thread, read by the main thread.
        self.is_moving  = False   # True whenever the robot body is moving
        self.is_touring = False   # True during the 35-metre campus tour

        # Callbacks — set these from robot.py before anything is sent.
        # on_obstacle(): called when Arduino sends OBSTACLE:...
        # on_done(cmd):  called when Arduino sends DONE:<cmd>
        self.on_obstacle = None
        self.on_done     = None

        self._connected = self._connect()
        if self._connected:
            t = threading.Thread(
                target=self._read_loop, daemon=True, name="arduino-reader")
            t.start()
        else:
            log.info("Running without Arduino — all motor commands are logged only.")

    # ---------------------------------------------------------------- connect

    def _connect(self):
        if not _HAS_SERIAL:
            log.warning(
                "pyserial is not installed — Arduino in mock mode. "
                "To enable motor control, run: pip install pyserial"
            )
            return False
        try:
            self._serial = pyserial.Serial(self.port, self.baud, timeout=1)
            # Arduino resets when the serial port opens; give it 2 s to boot.
            time.sleep(2.0)
            log.info("Arduino connected on %s at %d baud.", self.port, self.baud)
            return True
        except Exception as exc:
            log.warning(
                "Arduino not found on %s — motor control unavailable. (%s)",
                self.port, exc,
            )
            return False

    # ---------------------------------------------------------------- send

    def send(self, command: str):
        """Send a raw command string to the Arduino (newline appended)."""
        log.info("Arduino ← %s", command)
        if not self._connected or self._serial is None:
            log.debug("(mock) would send: %s", command)
            return
        try:
            with self._lock:
                self._serial.write((command.strip() + "\n").encode())
        except Exception as exc:
            log.error("Failed to send '%s' to Arduino: %s", command, exc)

    # ---------------------------------------------------------------- reader

    def _read_loop(self):
        """Background thread — reads lines from Arduino and updates state."""
        while True:
            try:
                if self._serial and self._serial.in_waiting:
                    raw = self._serial.readline().decode(errors="replace").strip()
                    if raw:
                        self._handle(raw)
                else:
                    time.sleep(0.05)
            except Exception as exc:
                log.error("Arduino read error: %s", exc)
                time.sleep(0.5)

    def _handle(self, msg: str):
        """Process one message received from the Arduino."""
        log.info("Arduino → %s", msg)

        if msg == "READY":
            log.info("Arduino is ready.")

        elif msg == "STATE:MOVING":
            self.is_moving = True

        elif msg == "STATE:PATH_CLEAR_RESUMING":
            self.is_moving = True   # still moving, obstacle cleared

        elif msg.startswith("DONE:"):
            cmd = msg[5:]           # e.g. "MOVEF" or "TOUR"
            self.is_moving = False
            if cmd == "TOUR":
                self.is_touring = False
            log.info("Arduino finished: %s", cmd)
            if self.on_done:
                self.on_done(cmd)

        elif msg.startswith("OBSTACLE:"):
            log.warning("Obstacle: %s", msg)
            if self.on_obstacle:
                self.on_obstacle()

        elif msg.startswith("ERROR:"):
            log.error("Arduino error: %s", msg)

    # ---------------------------------------------------------------- helpers

    def move_forward(self):
        self.is_moving = True
        self.send("MOVEF:1")

    def move_backward(self):
        self.is_moving = True
        self.send("MOVEB:1")

    def start_tour(self):
        self.is_moving  = True
        self.is_touring = True
        self.send("TOUR")

    def run_arm(self):
        self.send("ARM_RUN")

    def home_arm(self):
        self.send("ARM_HOME")

    def stop(self):
        self.is_moving  = False
        self.is_touring = False
        self.send("STOP")

    @property
    def connected(self):
        return self._connected

    def close(self):
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
