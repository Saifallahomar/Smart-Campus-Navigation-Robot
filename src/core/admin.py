"""
Admin / Settings page — PLACEHOLDER for a future feature.

Idea: a hidden on-screen settings page (opened with a key combo or a long-press
in a corner of the touchscreen) so settings can be changed without editing
config.json by hand. Useful for demos and for non-technical users.

Right now ALL settings live in config/config.json and are loaded by
config/settings.py — that is the single source of truth and works well. This
admin page would just be a friendlier front-end over the same values.

This file is NOT imported by the running robot yet. It documents the intended
shape so it can be built later without restructuring anything.

TODO (future):
  - A pygame overlay panel listing the common settings (language, volume,
    detection timeout, camera size, OpenAI models, audio devices).
  - Read current values from the `settings` object.
  - Write changes back to config/config.json (validate before saving).
  - Require a simple PIN so visitors cannot change settings during a demo.
  - NEVER show or edit secrets here — the API key stays in .env only.
"""

from src.utils.logging_setup import get_logger

log = get_logger("admin")


class AdminPage:
    """Placeholder settings page. Not active yet."""

    def __init__(self, settings=None):
        self.settings = settings

    def available(self) -> bool:
        """Return False until the admin page is implemented."""
        return False

    def open(self):
        """TODO: draw and handle the settings overlay. Currently a no-op."""
        log.info("Admin page requested, but it is not implemented yet.")
        return None
