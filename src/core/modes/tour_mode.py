"""
Campus Tour Mode — PLACEHOLDER for a future feature.

Idea: when a visitor says "give me a tour" the robot guides them through key
campus points (Library D Block, InfoHub, Engineering Z Block, BRL T Block,
Onezone food court, Students' Union U Block), speaking a short, friendly
description at each stop. On a future mobile base it could physically lead the
way; for now it would just narrate.

This file is NOT imported by the running robot yet. It only sketches the shape
so the feature can be added later without restructuring anything.

TODO (future):
  - Define the list of tour stops (reuse building facts from data/knowledge_base.md).
  - Speak each stop using the existing Assistant.synthesize() + Player.
  - Allow "next", "back", and "stop the tour" voice commands.
  - When a mobile base exists, drive between stops via a navigation module.
"""

from src.utils.logging_setup import get_logger

log = get_logger("tour_mode")


class TourMode:
    """Placeholder campus tour controller. Not active yet."""

    def __init__(self, assistant=None, player=None, knowledge=None):
        # These will be the same objects the main Robot already builds, so the
        # tour can talk using the existing voice pipeline when implemented.
        self.assistant = assistant
        self.player = player
        self.knowledge = knowledge

    def available(self) -> bool:
        """Return False until the tour is implemented."""
        return False

    def run(self):
        """TODO: implement the guided tour. Currently a safe no-op."""
        log.info("Tour mode requested, but it is not implemented yet.")
        return None
