# Smart Campus Navigation Robot

A friendly robot head that helps students and visitors around UWE Bristol. It
detects a person with its camera, listens, answers campus questions in their own
language, and talks back with an animated face on the 7-inch screen.

Built by **Saif Allah Omar** — Mechatronics, UWE Bristol.

---

## Features

- 🎤 AI voice conversation (speech-to-text → AI → text-to-speech)
- 🌍 Multilingual: replies in the language the user speaks
- 👀 Camera face detection — only listens when a person is present
- 🙂 Animated face with **emotions**: idle, listening, thinking, speaking, happy, confused
- 💬 On-screen captions — shows what you said and what the robot is saying
- 📷 Live camera preview thumbnail
- 🧠 UWE campus/student knowledge base (easy to edit)
- 🛡️ Robust error handling — recovers from network/API problems instead of crashing
- 📝 Logging to `logs/robot.log` for testing
- 🔌 Safe shutdown button on screen (and Esc on a keyboard)
- 🧭 Face tracking + head-controller interface, **ready for future servos**
- 🗣️ Optional wake word (off by default)

---

## Project structure

```
robot/
├── run.py                 # start here:  python run.py
├── start_robot.sh         # auto-start script for the Pi
├── requirements.txt
├── config/
│   ├── config.json        # all your settings (devices, language, features)
│   └── settings.py        # loads .env + config.json
├── data/
│   ├── knowledge_base.md  # the campus knowledge (edit this freely)
│   └── faq.json           # optional instant answers
├── src/
│   ├── core/   robot.py, states.py     # the main loop + emotions
│   ├── ui/     face.py, theme.py       # the animated face
│   ├── audio/  recorder.py, player.py, wakeword.py
│   ├── vision/ camera.py, tracker.py   # face detection + tracking
│   ├── ai/     assistant.py, knowledge.py
│   ├── hardware/ head_controller.py    # servo prep (no motors yet)
│   └── utils/  logging_setup.py
├── legacy/                # all the old scripts/backups (kept for reference)
└── logs/                  # created automatically
```

---

## Setup on the Raspberry Pi

```bash
# 1. Get the code
git clone https://github.com/Saifallahomar/Smart-Campus-Navigation-Robot.git
cd Smart-Campus-Navigation-Robot

# 2. Create a virtual environment WITH system packages (so picamera2 works)
python -m venv venv --system-site-packages
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your secret key
cp .env.example .env
nano .env          # paste your OPENAI_API_KEY

# 5. Run it
python run.py
```

Press the red power button on screen (or **Esc**) to stop.

---

## Configuration

Edit **`config/config.json`** — no code changes needed. Key options:

| Setting | What it does |
|---|---|
| `mock_mode` | `true` runs the face only, no camera/mic (great for a laptop) |
| `devices.mic_device` | Microphone index (default `1`) |
| `devices.speaker_device` | ALSA speaker (default `plughw:2,0`) |
| `audio.voice_threshold` | How loud counts as speech |
| `vision.show_preview` | Show the camera thumbnail |
| `vision.track_face` | Feed face position to the head controller |
| `ai.use_local_faq` | Use instant local answers for common English questions |
| `wake_word.enabled` | Turn on the "hey robot" wake word |
| `ui.shutdown_action` | `quit` (stop program) or `poweroff` (shut down the Pi) |

Secrets (API keys) go in **`.env`**, never in `config.json`.

---

## 🔒 Security — important

The `.env` file holds your OpenAI key and is **ignored by git**. Never commit it.

This key was previously committed to the public repo. Removing it from new
commits does **not** remove it from git history, so:

1. **Strongly recommended:** revoke the old key at
   <https://platform.openai.com/api-keys> and create a new one. This is the only
   guaranteed fix once a key has been public.
2. To also scrub it from history (then force-push), e.g. with
   [git filter-repo](https://github.com/newren/git-filter-repo):

   ```bash
   pip install git-filter-repo
   git filter-repo --path .env --path .env.save --invert-paths
   git push --force --all
   ```

---

## Future development

The structure is ready for the next steps:

- **Head movement / person following** — `src/hardware/head_controller.py` already
  receives `aim(dx, dy)` from the face tracker. Subclass it and drive servos in
  `_apply()`; nothing else needs to change.
- **Campus tours / navigation** — add a module under `src/core/` and call it from
  the main loop in `robot.py`.
- **Wake word** — set `wake_word.engine` to `porcupine`, add `PORCUPINE_ACCESS_KEY`
  to `.env`, and list keyword files in `config.json`.

---

## Troubleshooting

- **No sound** → check `devices.speaker_device`; list devices with `aplay -l`.
- **Mic not heard** → check `devices.mic_device`; list with `python -c "import sounddevice; print(sounddevice.query_devices())"`.
- **Camera errors** → ensure the venv was made with `--system-site-packages`.
- **AI says it can't connect** → check `.env` has a valid `OPENAI_API_KEY` and the Pi has internet.
- Check `logs/robot.log` for details after any issue.
