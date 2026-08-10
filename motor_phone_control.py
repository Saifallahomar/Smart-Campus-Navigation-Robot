"""
Motor phone control — standalone web server for remote control via phone/browser.

Run with:
    python motor_phone_control.py

Then open  http://<Pi-IP-address>:5000  on your phone.

This is SEPARATE from run.py.  Do NOT run both at the same time — they would
both try to open the same Arduino serial port (/dev/ttyACM0) and one would fail.

  run.py                 = AI voice assistant + motor commands via voice
  motor_phone_control.py = manual phone/browser D-pad control only

Requires Flask:
    pip install flask
"""

import sys
import time

# ── Serial (Arduino) ────────────────────────────────────────────────────────

SERIAL_PORT = "/dev/ttyACM0"
BAUD_RATE   = 9600

arduino = None

try:
    import serial as pyserial
    try:
        arduino = pyserial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)   # wait for Arduino to reset after serial opens
        print(f"[Motor Control] Connected to Arduino on {SERIAL_PORT}")
    except Exception as e:
        print(f"[Motor Control] WARNING: Arduino not found on {SERIAL_PORT} — {e}")
        print("[Motor Control] Running without Arduino. Commands will be logged only.")
except ImportError:
    print("[Motor Control] WARNING: pyserial not installed. Run: pip install pyserial")
    print("[Motor Control] Running without Arduino. Commands will be logged only.")


def send_command(cmd: str):
    """Send a single command character/string to the Arduino."""
    print(f"[Motor Control] Sent: {cmd}")
    if arduino and arduino.is_open:
        try:
            arduino.write((cmd + "\n").encode())
        except Exception as e:
            print(f"[Motor Control] Send error: {e}")


# ── Flask web server ─────────────────────────────────────────────────────────

try:
    from flask import Flask, request, jsonify
except ImportError:
    print("[Motor Control] ERROR: Flask not installed.")
    print("Install it with:  pip install flask")
    sys.exit(1)

app = Flask(__name__)

# ── Web page (served inline — no templates folder needed) ────────────────────

PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <title>Robot Control</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: #111;
      color: #eee;
      font-family: Arial, sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 20px 10px;
      min-height: 100vh;
      user-select: none;
    }

    h1 { font-size: 1.3rem; margin-bottom: 6px; color: #4fc3f7; }
    #status { font-size: 0.85rem; color: #aaa; margin-bottom: 20px; }

    /* ─── D-pad ─────────────────────────────────── */
    .dpad {
      display: grid;
      grid-template-columns: repeat(3, 80px);
      grid-template-rows: repeat(3, 80px);
      gap: 8px;
      margin-bottom: 20px;
    }
    .btn {
      background: #1e1e1e;
      border: 2px solid #444;
      border-radius: 12px;
      color: #eee;
      font-size: 2rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.1s, transform 0.1s;
      -webkit-tap-highlight-color: transparent;
    }
    .btn:active, .btn.pressed {
      background: #2979ff;
      border-color: #2979ff;
      transform: scale(0.93);
    }
    .stop-btn {
      background: #b71c1c;
      border-color: #ef5350;
      font-size: 1.1rem;
      font-weight: bold;
    }
    .stop-btn:active, .stop-btn.pressed {
      background: #ef5350;
    }
    .empty { background: transparent; border: none; pointer-events: none; }

    /* ─── Speed row ─────────────────────────────── */
    .speed-row {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: center;
      margin-bottom: 20px;
    }
    .speed-btn {
      width: 44px;
      height: 44px;
      border-radius: 8px;
      font-size: 1rem;
    }

    /* ─── Log ────────────────────────────────────── */
    #log {
      width: 100%;
      max-width: 340px;
      background: #1a1a1a;
      border-radius: 8px;
      padding: 10px;
      font-size: 0.78rem;
      color: #80cbc4;
      height: 120px;
      overflow-y: auto;
      font-family: monospace;
    }
  </style>
</head>
<body>

  <h1>&#129302; Robot Control</h1>
  <div id="status">Connecting...</div>

  <!-- D-pad -->
  <div class="dpad">
    <div class="empty"></div>
    <button class="btn" id="btn-F" ontouchstart="press('F')" ontouchend="release()" onmousedown="press('F')" onmouseup="release()">&#8593;</button>
    <div class="empty"></div>

    <button class="btn" id="btn-L" ontouchstart="press('L')" ontouchend="release()" onmousedown="press('L')" onmouseup="release()">&#8592;</button>
    <button class="btn stop-btn" id="btn-S" ontouchstart="press('S')" ontouchend="noRelease()" onmousedown="press('S')" onmouseup="noRelease()">STOP</button>
    <button class="btn" id="btn-R" ontouchstart="press('R')" ontouchend="release()" onmousedown="press('R')" onmouseup="release()">&#8594;</button>

    <div class="empty"></div>
    <button class="btn" id="btn-B" ontouchstart="press('B')" ontouchend="release()" onmousedown="press('B')" onmouseup="release()">&#8595;</button>
    <div class="empty"></div>
  </div>

  <!-- Speed -->
  <div class="speed-row">
    <span style="line-height:44px;margin-right:4px;font-size:0.85rem;">Speed:</span>
    <button class="btn speed-btn" onclick="send('1')">1</button>
    <button class="btn speed-btn" onclick="send('2')">2</button>
    <button class="btn speed-btn" onclick="send('3')">3</button>
    <button class="btn speed-btn" onclick="send('4')">4</button>
    <button class="btn speed-btn" onclick="send('5')">5</button>
    <button class="btn speed-btn" onclick="send('6')">6</button>
    <button class="btn speed-btn" onclick="send('7')">7</button>
    <button class="btn speed-btn" onclick="send('8')">8</button>
    <button class="btn speed-btn" onclick="send('9')">9</button>
  </div>

  <div id="log"></div>

<script>
  let currentCmd = null;
  let holdTimer   = null;

  function log(msg) {
    const el = document.getElementById('log');
    const line = document.createElement('div');
    line.textContent = new Date().toLocaleTimeString() + ' ' + msg;
    el.prepend(line);
    if (el.children.length > 30) el.removeChild(el.lastChild);
  }

  function send(cmd) {
    fetch('/cmd', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cmd: cmd})
    })
    .then(r => r.json())
    .then(d => {
      document.getElementById('status').textContent = 'Last: ' + d.cmd;
      log('Sent: ' + d.cmd);
    })
    .catch(() => {
      document.getElementById('status').textContent = 'Connection error';
      log('ERROR: could not send');
    });
  }

  function press(cmd) {
    // Highlight button
    const btn = document.getElementById('btn-' + cmd);
    if (btn) btn.classList.add('pressed');

    if (cmd === currentCmd) return;
    currentCmd = cmd;
    send(cmd);
    // Repeat while held
    holdTimer = setInterval(() => send(cmd), 300);
  }

  function release() {
    if (currentCmd && currentCmd !== 'S') {
      send('S');   // auto-stop on release
    }
    clearInterval(holdTimer);
    holdTimer = null;
    currentCmd = null;
    document.querySelectorAll('.btn').forEach(b => b.classList.remove('pressed'));
  }

  function noRelease() {
    // Stop button — don't auto-send S again on release
    clearInterval(holdTimer);
    holdTimer = null;
    currentCmd = null;
    document.querySelectorAll('.btn').forEach(b => b.classList.remove('pressed'));
  }

  // Check connection on load
  fetch('/ping').then(r => r.json()).then(d => {
    document.getElementById('status').textContent =
      d.arduino ? 'Arduino connected' : 'No Arduino (mock mode)';
  }).catch(() => {
    document.getElementById('status').textContent = 'Cannot reach server';
  });
</script>
</body>
</html>
"""


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return PAGE_HTML


@app.route("/ping")
def ping():
    return jsonify({"ok": True, "arduino": arduino is not None and arduino.is_open})


@app.route("/cmd", methods=["POST"])
def cmd():
    data = request.get_json(silent=True) or {}
    command = str(data.get("cmd", "")).strip().upper()

    # Whitelist — only allow known safe commands.
    allowed = set("FBLRS0123456789")
    if not command or command not in allowed:
        return jsonify({"error": "unknown command", "cmd": command}), 400

    send_command(command)
    return jsonify({"ok": True, "cmd": command})


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[Motor Control] Motor web server starting")
    if arduino and arduino.is_open:
        print(f"[Motor Control] Connected to Arduino on {SERIAL_PORT}")
    else:
        print(f"[Motor Control] No Arduino — running in log-only mode")
    print("[Motor Control] Running on http://0.0.0.0:5000")
    print("[Motor Control] Open that address on your phone to control the robot")
    print("[Motor Control] Press Ctrl+C to stop\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
