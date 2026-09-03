"""
Phone motor control web server — runs as a background daemon thread inside run.py.

Shares the same ArduinoController and CameraFeed that the main robot already
uses.  No second serial port or camera is opened.

Access from your phone:  http://<Pi-IP-address>:5000

The page shows:
  - Live camera feed (MJPEG stream from the Pi Camera)
  - D-pad: F / B / L / R
  - STOP button
  - Speed buttons 1-9
  - Arduino / camera connection status
"""

import logging
import threading
import time

from src.utils.logging_setup import get_logger

log = get_logger("phone_server")

# Keep Flask/werkzeug quiet — only log errors, not every HTTP request.
logging.getLogger("werkzeug").setLevel(logging.ERROR)

try:
    from flask import Flask, Response, request, jsonify
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False

# Whitelist — only these characters may be forwarded to the Arduino.
_ALLOWED = set("FBLRS0123456789")

# ---------------------------------------------------------------------------
# HTML page (inline — no templates/ folder needed)
# ---------------------------------------------------------------------------

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
  <title>Robot Control</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: #0d0d0d;
      color: #e0e0e0;
      font-family: Arial, sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 14px;
      padding: 12px 8px 20px;
      min-height: 100vh;
      user-select: none;
      -webkit-user-select: none;
    }

    h1 { font-size: 1.15rem; color: #4fc3f7; letter-spacing: 0.04em; }

    /* ── Status bar ── */
    #status-bar {
      display: flex;
      gap: 10px;
      font-size: 0.75rem;
      color: #888;
    }
    .dot { display: inline-block; width: 8px; height: 8px;
           border-radius: 50%; background: #555; margin-right: 4px; }
    .dot.green { background: #4caf50; }
    .dot.red   { background: #f44336; }

    /* ── Camera ── */
    #cam-wrap {
      width: 100%;
      max-width: 400px;
      background: #1a1a1a;
      border-radius: 10px;
      overflow: hidden;
      aspect-ratio: 4/3;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
    }
    #cam-wrap img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    #cam-err {
      display: none;
      color: #666;
      font-size: 0.85rem;
      text-align: center;
      padding: 10px;
    }
    #last-cmd {
      position: absolute;
      bottom: 6px; right: 8px;
      background: rgba(0,0,0,0.55);
      color: #4fc3f7;
      font-size: 0.72rem;
      padding: 2px 6px;
      border-radius: 4px;
    }

    /* ── D-pad ── */
    .dpad {
      display: grid;
      grid-template-columns: repeat(3, 72px);
      grid-template-rows: repeat(3, 72px);
      gap: 6px;
    }
    .btn {
      background: #1e1e1e;
      border: 2px solid #333;
      border-radius: 10px;
      color: #ddd;
      font-size: 1.8rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.08s, transform 0.08s;
      -webkit-tap-highlight-color: transparent;
      touch-action: manipulation;
    }
    .btn:active, .btn.on {
      background: #1565c0;
      border-color: #42a5f5;
      transform: scale(0.92);
    }
    .stop-btn {
      background: #7f0000;
      border-color: #ef5350;
      font-size: 1rem;
      font-weight: bold;
      letter-spacing: 0.05em;
    }
    .stop-btn:active, .stop-btn.on {
      background: #c62828;
      border-color: #ef9a9a;
    }
    .ghost { visibility: hidden; pointer-events: none; }

    /* ── Speed row ── */
    .speed-row {
      display: flex;
      gap: 5px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: center;
    }
    .speed-lbl { font-size: 0.8rem; color: #888; margin-right: 2px; }
    .speed-btn {
      width: 38px; height: 38px;
      border-radius: 6px;
      font-size: 0.95rem;
    }

    /* ── Log ── */
    #log {
      width: 100%;
      max-width: 400px;
      background: #111;
      border-radius: 8px;
      padding: 8px 10px;
      height: 80px;
      overflow-y: auto;
      font-family: monospace;
      font-size: 0.72rem;
      color: #4db6ac;
    }
  </style>
</head>
<body>

<h1>&#129302; Robot Control</h1>

<div id="status-bar">
  <span><span class="dot" id="dot-ard"></span><span id="lbl-ard">Arduino</span></span>
  <span><span class="dot" id="dot-cam"></span><span id="lbl-cam">Camera</span></span>
</div>

<!-- Camera feed -->
<div id="cam-wrap">
  <img id="cam-img" src="/video"
       onerror="camError()" onload="camOk()">
  <div id="cam-err">&#128247; Camera unavailable</div>
  <div id="last-cmd"></div>
</div>

<!-- D-pad -->
<div class="dpad">
  <div class="ghost"></div>
  <button class="btn" id="btn-F"
    ontouchstart="press('F',event)" ontouchend="release(event)"
    onmousedown="press('F',event)"  onmouseup="release(event)">&#8593;</button>
  <div class="ghost"></div>

  <button class="btn" id="btn-L"
    ontouchstart="press('L',event)" ontouchend="release(event)"
    onmousedown="press('L',event)"  onmouseup="release(event)">&#8592;</button>
  <button class="btn stop-btn" id="btn-S"
    ontouchstart="pressStop(event)" ontouchend="releaseStop(event)"
    onmousedown="pressStop(event)"  onmouseup="releaseStop(event)">STOP</button>
  <button class="btn" id="btn-R"
    ontouchstart="press('R',event)" ontouchend="release(event)"
    onmousedown="press('R',event)"  onmouseup="release(event)">&#8594;</button>

  <div class="ghost"></div>
  <button class="btn" id="btn-B"
    ontouchstart="press('B',event)" ontouchend="release(event)"
    onmousedown="press('B',event)"  onmouseup="release(event)">&#8595;</button>
  <div class="ghost"></div>
</div>

<!-- Speed -->
<div class="speed-row">
  <span class="speed-lbl">Speed:</span>
  <button class="btn speed-btn" onclick="sendCmd('1')">1</button>
  <button class="btn speed-btn" onclick="sendCmd('2')">2</button>
  <button class="btn speed-btn" onclick="sendCmd('3')">3</button>
  <button class="btn speed-btn" onclick="sendCmd('4')">4</button>
  <button class="btn speed-btn" onclick="sendCmd('5')">5</button>
  <button class="btn speed-btn" onclick="sendCmd('6')">6</button>
  <button class="btn speed-btn" onclick="sendCmd('7')">7</button>
  <button class="btn speed-btn" onclick="sendCmd('8')">8</button>
  <button class="btn speed-btn" onclick="sendCmd('9')">9</button>
</div>

<div id="log"></div>

<script>
  let active = null;
  let timer  = null;

  /* ── Camera ─────────────────────────────────── */
  function camError() {
    document.getElementById('cam-img').style.display = 'none';
    document.getElementById('cam-err').style.display = 'block';
    setDot('cam', false);
  }
  function camOk() {
    document.getElementById('cam-err').style.display = 'none';
    setDot('cam', true);
  }

  /* ── Status dots ─────────────────────────────── */
  function setDot(which, ok) {
    const d = document.getElementById('dot-' + which);
    if (d) { d.className = 'dot ' + (ok ? 'green' : 'red'); }
  }

  /* ── Logging ─────────────────────────────────── */
  function addLog(msg) {
    const el = document.getElementById('log');
    const row = document.createElement('div');
    row.textContent = new Date().toLocaleTimeString() + '  ' + msg;
    el.prepend(row);
    while (el.children.length > 25) el.removeChild(el.lastChild);
  }

  /* ── Send command ────────────────────────────── */
  function sendCmd(cmd) {
    fetch('/cmd', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cmd})
    })
    .then(r => r.json())
    .then(d => {
      document.getElementById('last-cmd').textContent = 'Last: ' + d.cmd;
      addLog('Sent: ' + d.cmd);
    })
    .catch(() => addLog('ERROR: no response'));
  }

  /* ── D-pad hold ──────────────────────────────── */
  function press(cmd, e) {
    e.preventDefault();
    if (active === cmd) return;
    active = cmd;
    highlight(cmd, true);
    sendCmd(cmd);
    timer = setInterval(() => sendCmd(cmd), 250);
  }

  function release(e) {
    e.preventDefault();
    clearInterval(timer); timer = null;
    if (active && active !== 'S') sendCmd('S');
    highlight(active, false);
    active = null;
  }

  function pressStop(e) {
    e.preventDefault();
    clearInterval(timer); timer = null;
    active = 'S';
    highlight('S', true);
    sendCmd('S');
  }

  function releaseStop(e) {
    e.preventDefault();
    highlight('S', false);
    active = null;
  }

  function highlight(cmd, on) {
    const b = document.getElementById('btn-' + cmd);
    if (b) b.classList.toggle('on', on);
  }

  /* ── Ping on load ─────────────────────────────── */
  fetch('/ping')
    .then(r => r.json())
    .then(d => {
      setDot('ard', d.arduino);
      setDot('cam', d.camera);
      addLog('Server connected. Arduino: ' + (d.arduino ? 'yes' : 'no') +
             ', Camera: ' + (d.camera ? 'yes' : 'no'));
    })
    .catch(() => addLog('Cannot reach server'));
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Server class
# ---------------------------------------------------------------------------

class PhoneControlServer:
    """
    Flask web server that shares the robot's Arduino and camera.

    Usage in robot.py::

        self.phone_server = PhoneControlServer(
            arduino=self.arduino,
            camera_feed=self.feed,
            port=5000,
        )
        # Call start() after camera.start() and feed.start():
        self.phone_server.start()
    """

    def __init__(self, arduino, camera_feed, port: int = 5000):
        self.arduino = arduino
        self.feed    = camera_feed
        self.port    = port

    def start(self):
        """Launch the server in a daemon background thread."""
        if not _HAS_FLASK:
            log.warning(
                "Flask not installed — phone motor control unavailable. "
                "Install with: pip install flask"
            )
            return
        t = threading.Thread(
            target=self._serve, daemon=True, name="phone-server")
        t.start()
        log.info("Phone motor control server started on port %d", self.port)
        log.info("Open  http://<Pi-IP>:%d  on your phone.", self.port)

    # ---------------------------------------------------------------- Flask

    def _serve(self):
        app = self._build_app()
        app.run(
            host="0.0.0.0",
            port=self.port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    def _build_app(self):
        app  = Flask(__name__)
        ardu = self.arduino
        feed = self.feed

        @app.route("/")
        def index():
            return _PAGE

        @app.route("/ping")
        def ping():
            return jsonify(
                arduino=bool(getattr(ardu, "connected", False)),
                camera=bool(getattr(feed, "available", False)),
            )

        @app.route("/cmd", methods=["POST"])
        def cmd():
            data = request.get_json(silent=True) or {}
            c    = str(data.get("cmd", "")).strip().upper()
            if not c or c not in _ALLOWED:
                return jsonify(error="unknown command", cmd=c), 400
            log.info("Phone command received: %s", c)
            ardu.send(c)
            return jsonify(ok=True, cmd=c)

        @app.route("/video")
        def video():
            return Response(
                _mjpeg_stream(feed),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )

        return app


# ---------------------------------------------------------------------------
# MJPEG stream helper (module-level so Flask can pickle it cleanly)
# ---------------------------------------------------------------------------

def _mjpeg_stream(feed):
    """Yield MJPEG-encoded frames from the shared CameraFeed."""
    while True:
        frame = getattr(feed, "frame", None)
        if frame is None:
            time.sleep(0.1)
            continue
        try:
            import cv2
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            ok, buf = cv2.imencode(
                ".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 65])
            if ok:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + buf.tobytes()
                    + b"\r\n"
                )
        except Exception as exc:
            log.debug("Frame encode error: %s", exc)
        time.sleep(0.07)   # ~14 fps — enough for a driving preview
