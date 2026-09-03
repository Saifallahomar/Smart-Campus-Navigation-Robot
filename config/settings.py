"""
Central settings for the robot.

Loads secrets from the .env file and runtime options from config/config.json.
Everything else in the project imports the ready-to-use ``settings`` object from
here, so there is a single place that knows where files live and what the
defaults are.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Project layout (config/settings.py -> project root is one level up).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"

# Load secrets from .env (if it exists). Missing file is fine - we warn later.
load_dotenv(PROJECT_ROOT / ".env")


# Safe fallback defaults. These mirror the original working robot so the program
# still runs even if config.json is missing or partially filled in.
DEFAULTS = {
    "mock_mode": False,
    "language": "auto",
    "devices": {
        "mic_device": 1,
        "speaker_device": "plughw:2,0",
        "mic_auto_detect_name": "EMEET",
        "speaker_auto_detect": False,
    },
    "audio": {
        "sample_rate": 16000,
        "chunk_seconds": 0.2,
        "voice_threshold": 500,
        "silence_to_stop": 0.9,
        "max_record_seconds": 10,
    },
    "vision": {
        "enabled": True,
        "frame_width": 640,
        "frame_height": 480,
        "cascade_path": "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
        "scale_factor": 1.2,
        "min_neighbors": 5,
        "min_face_size": 60,
        "show_preview": True,
        "track_face": True,
        "feed_fps": 15,
    },
    "ai": {
        "chat_model": "gpt-4o-mini",
        "transcribe_model": "gpt-4o-mini-transcribe",
        "tts_model": "gpt-4o-mini-tts",
        "tts_voice": "fable",
        # Accent / delivery styling. Affects HOW the robot speaks, not what it
        # says. Silently ignored by models that do not support instructions.
        "tts_instructions": (
            "Speak in a warm, clear British English accent, like a friendly UK "
            "university campus guide at UWE Bristol. Sound welcoming, natural "
            "and unhurried, never rushed or robotic. If the text is in Arabic, "
            "French, or Chinese, speak it naturally in that language with a "
            "native accent instead."
        ),
        "max_history_turns": 12,
        "use_local_faq": False,
        "request_timeout": 30,
        "max_retries": 2,
    },
    "wake_word": {
        "enabled": False,
        "engine": "energy",
        "keywords": ["hey robot", "hello robot"],
        "porcupine_keyword_paths": [],
    },
    "ui": {
        "show_captions": True,
        "fullscreen": True,
        "fps": 30,
        "shutdown_action": "quit",  # "quit" = just stop the program; "poweroff" = shut down the Pi
        "portrait": False,
        "preview_height_frac": 0.45,
        "face_height_frac": 0.29,
        # Mirror the on-screen preview so it looks like a selfie camera.
        # Detection (face boxes, gaze, wave, vision) still uses the original frame.
        "mirror_preview": True,
    },
    "conversation": {
        # Seconds a person can be absent before the session ends.
        "person_lost_timeout": 8,
        # Maximum seconds for one session (null = unlimited).
        "max_session_seconds": None,
        # What the robot says at the end of a session.
        "farewell_message": "Bye! Have a great day!",
    },
    "question_logging": {
        # Optional CSV log of questions and answers. Text only — no audio or images.
        "enabled": False,
    },
    "wave_detection": {
        # Lightweight frame-differencing wave detector. Shows "User is waving".
        "enabled": True,
        # Pixel difference needed to count as motion (0-255, higher = less sensitive).
        "motion_threshold": 30,
        # How many consecutive motion frames before a wave is confirmed.
        "min_motion_frames": 8,
        # Minimum seconds between consecutive wave events.
        "cooldown_seconds": 3.0,
    },
    "servo": {
        # Single pan servo that turns the head to follow a face.
        "enabled": True,
        # Signal pin (BCM numbering). GPIO 18 = physical pin 12.
        "gpio_pin": 18,
        # Safe sweep range in degrees.
        "min_angle": -90,
        "max_angle": 90,
        "center_angle": 0,
        # How far "look left"/"look right" turn from centre (safe limit).
        "voice_look_angle_deg": 60,
        # Fraction of remaining distance moved per tick (lower = gentler glide).
        "smoothing": 0.12,
        # How fast the head may turn (smaller = slower/gentler).
        "max_speed_deg_per_sec": 60,
        # How close counts as "arrived" (then it stops).
        "deadzone_deg": 2.0,
        # How big a change must be to start moving again (> deadzone = no twitch).
        "wake_zone_deg": 5.0,
        # Once settled, wait this long then stop pulsing so the servo is silent.
        "idle_release_seconds": 1.5,
        # After a person leaves, wait this long then return the head to centre.
        "recenter_delay_seconds": 1.5,
        # Flip if the head turns the wrong way.
        "invert": False,
        # Pulse widths (ms) — defaults suit a typical SG90.
        "min_pulse_width_ms": 0.5,
        "max_pulse_width_ms": 2.5,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into a copy of ``base``."""
    result = dict(base)
    for key, value in override.items():
        if key.startswith("_"):  # skip "_comment" style helper keys
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    """Read-only view over merged defaults + user config + secrets."""

    def __init__(self):
        self._data = self._load_config()

        # Secrets come from the environment, never from config.json.
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.porcupine_access_key = os.getenv("PORCUPINE_ACCESS_KEY")

        # Convenient absolute paths.
        self.project_root = PROJECT_ROOT
        self.data_dir = DATA_DIR
        self.log_dir = LOG_DIR
        self.knowledge_base_path = DATA_DIR / "knowledge_base.md"
        self.faq_path = DATA_DIR / "faq.json"

    def _load_config(self) -> dict:
        data = json.loads(json.dumps(DEFAULTS))  # deep copy
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    user = json.load(f)
                data = _deep_merge(data, user)
            except (json.JSONDecodeError, OSError) as exc:
                # Don't crash on a broken config - fall back to defaults.
                print(f"[settings] Could not read config.json ({exc}); using defaults.")
        return data

    def get(self, *keys, default=None):
        """Look up a nested value, e.g. settings.get('audio', 'sample_rate')."""
        node = self._data
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    # Frequently used sections exposed as simple attributes.
    @property
    def mock_mode(self) -> bool:
        return bool(self._data.get("mock_mode", False))

    @property
    def devices(self) -> dict:
        return self._data["devices"]

    @property
    def audio(self) -> dict:
        return self._data["audio"]

    @property
    def vision(self) -> dict:
        return self._data["vision"]

    @property
    def ai(self) -> dict:
        return self._data["ai"]

    @property
    def wake_word(self) -> dict:
        return self._data["wake_word"]

    @property
    def ui(self) -> dict:
        return self._data["ui"]


# Singleton used across the project.
settings = Settings()
