"""
Navigation Mode — PLACEHOLDER for a future feature.

Idea: a visitor asks "how do I get to the Library?" and the robot gives clear,
step-by-step walking directions from where it stands to the destination block.

Two future levels:
  1. Spoken directions only (no movement) — achievable with a simple map of
     campus blocks and the paths between them.
  2. Physical guidance — only once the robot has a mobile base, wheel encoders,
     and obstacle sensors. That is a large, separate project.

This file is NOT imported by the running robot yet. It documents the intended
shape so it can be built later without restructuring anything.

TODO (future):
  - Build a small campus graph: blocks as nodes, walkable paths as edges.
  - Given a destination, find a route and turn it into short spoken steps.
  - Reuse building facts from data/knowledge_base.md so directions stay accurate.
  - SAFETY: physical movement needs obstacle detection and an emergency stop
    before it is ever enabled.
"""

from src.utils.logging_setup import get_logger

log = get_logger("navigation_mode")


class NavigationMode:
    """Placeholder navigation controller. Not active yet."""

    def __init__(self, assistant=None, player=None, knowledge=None):
        self.assistant = assistant
        self.player = player
        self.knowledge = knowledge

    def available(self) -> bool:
        """Return False until navigation is implemented."""
        return False

    def directions_to(self, destination):
        """TODO: return spoken step-by-step directions. Currently a no-op."""
        log.info("Directions to %r requested, but navigation is not implemented yet.",
                 destination)
        return None
