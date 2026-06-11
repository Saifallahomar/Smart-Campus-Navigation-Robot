"""
The robot's emotional / activity states.

These drive both the face on screen (colours, eye and mouth shapes) and the
status text shown to the user. Keeping them in one enum means the UI and the
logic always agree on what "thinking" or "listening" means.
"""

from enum import Enum


class RobotState(Enum):
    IDLE = "idle"                    # waiting, calm, blinking
    FACE_DETECTED = "face_detected"  # a person was just noticed
    LISTENING = "listening"          # microphone is recording the user
    THINKING = "thinking"            # transcribing / asking the AI
    SPEAKING = "speaking"            # talking back to the user
    HAPPY = "happy"                  # friendly greeting / positive answer
    CONFUSED = "confused"            # didn't understand / fallback answer
    ERROR = "error"                  # network / API failure

    @property
    def status_text(self) -> str:
        """Short label shown on screen for this state."""
        return {
            "idle": "",
            "face_detected": "Hello!",
            "listening": "Listening...",
            "thinking": "Thinking...",
            "speaking": "Speaking...",
            "happy": "",
            "confused": "Hmm...",
            "error": "No internet",
        }[self.value]
