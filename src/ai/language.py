"""
Language detection for the robot's three supported languages: English, Arabic, French.

Uses Unicode range analysis (Arabic) and keyword matching (French).
No extra libraries needed — works with standard Python.

Called BEFORE the AI so garbled STT output or unsupported scripts are
caught cheaply and the robot never accidentally replies in a random language.
"""

# ---------------------------------------------------------------------------
# Unicode character ranges
# ---------------------------------------------------------------------------

_ARABIC_RANGES = [
    ('؀', 'ۿ'),  # Arabic main block
    ('ݐ', 'ݿ'),  # Arabic Supplement
    ('ﭐ', '﷿'),  # Arabic Presentation Forms-A
    ('ﹰ', '﻿'),  # Arabic Presentation Forms-B
]

# Scripts that are clearly not English, Arabic, or French.
# If a significant share of the transcript is in these ranges, reject it.
_UNSUPPORTED_RANGES = [
    ('Ѐ', 'ӿ'),  # Cyrillic (Russian, Bulgarian, …)
    ('֐', '׿'),  # Hebrew
    ('ऀ', 'ॿ'),  # Devanagari (Hindi, Marathi, …)
    ('ঀ', '৿'),  # Bengali
    ('฀', '๿'),  # Thai
    ('က', '႟'),  # Myanmar/Burmese
    ('　', '鿿'),  # CJK: Chinese, Japanese, Korean ideographs
    ('가', '힯'),  # Hangul (Korean syllables)
    ('ꀀ', '꒏'),  # Yi
]

# ---------------------------------------------------------------------------
# French vocabulary
# ---------------------------------------------------------------------------

# Single match is enough to flag French.
_FRENCH_STRONG = {
    'bonjour', 'bonsoir', 'bonne', 'salut', 'merci', 'beaucoup',
    'voulez', 'pouvez', 'voudrais', 'parlez', 'parle',
    'français', 'française', 'bibliothèque', 'bâtiment',
    'étudiant', 'étudiante', 'université',
    'où', 'êtes', 'sommes', 'pourquoi', 'combien',
    'cherche', 'besoin', 'aidez', 'aide',
}

# Two or more of these together indicate French.
_FRENCH_WEAK = {
    'je', 'tu', 'il', 'elle', 'nous', 'vous', 'ils', 'elles',
    'oui', 'non', 'avec', 'pour', 'dans', 'sur', 'que', 'qui',
    'est', 'sont', 'une', 'les', 'des', 'aller', 'avoir', 'faire',
    'comment', 'quand', 'trouver', 'salle', 'bloc', 'suis',
}

# ---------------------------------------------------------------------------
# Canned replies (used without calling the AI)
# ---------------------------------------------------------------------------

UNSUPPORTED_REPLY = (
    "I'm sorry, I only understand English, Arabic, and French. "
    "Could you please repeat in one of these languages?"
)

LANGUAGE_NAMES = {
    'english': 'English',
    'arabic':  'Arabic',
    'french':  'French',
}

# Short, friendly canned lines the robot can SAY when something goes wrong,
# without needing the AI. Keyed by situation, then by language so the spoken
# reply still matches the three supported languages. English is the default.
FALLBACK_PHRASES = {
    # Speech-to-text failed or produced nothing usable.
    'didnt_catch': {
        'english': "Sorry, I didn't quite catch that. Could you say it again?",
        'arabic':  "عذرًا، لم أسمع ذلك جيدًا. هل يمكنك إعادة قول ذلك؟",
        'french':  "Désolé, je n'ai pas bien entendu. Pouvez-vous répéter ?",
    },
}


def fallback_phrase(situation: str, language: str = 'english') -> str:
    """
    Return a friendly canned line for a situation in the given language.

    Falls back to English if the situation or language is unknown, so this
    never raises and always returns something speakable.
    """
    options = FALLBACK_PHRASES.get(situation, {})
    return options.get(language) or options.get('english') \
        or "Sorry, could you please repeat that?"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_in_ranges(text: str, ranges: list) -> int:
    total = 0
    for ch in text:
        for lo, hi in ranges:
            if lo <= ch <= hi:
                total += 1
                break
    return total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """
    Return 'arabic', 'french', or 'english' (the default fallback).

    Uses Unicode proportion for Arabic and keyword matching for French.
    All other Latin-script text is treated as English.
    """
    if not text or not text.strip():
        return 'english'

    no_space = text.replace(' ', '').replace('\n', '').replace('\t', '')
    total = max(len(no_space), 1)

    # Arabic: more than 15% of non-whitespace chars are in Arabic Unicode
    if _count_in_ranges(no_space, _ARABIC_RANGES) / total > 0.15:
        return 'arabic'

    # French: vocabulary matching
    words = set(text.lower().split())
    if (words & _FRENCH_STRONG) or len(words & _FRENCH_WEAK) >= 2:
        return 'french'

    return 'english'


def is_supported_input(text: str) -> bool:
    """
    Return False if the text appears to be in an unsupported script.

    Catches Cyrillic, CJK, Hebrew, Hindi, Thai, etc.
    Arabic and Latin-Extended (French accents) are allowed through.
    Also rejects text that contains too few alphabetic characters
    (sign of garbled/noise STT output).
    """
    if not text or not text.strip():
        return False

    # Must contain at least 2 alphabetic characters to count as real speech
    if sum(1 for c in text if c.isalpha()) < 2:
        return False

    no_space = text.replace(' ', '').replace('\n', '')
    total = max(len(no_space), 1)

    unsupported = _count_in_ranges(no_space, _UNSUPPORTED_RANGES)
    if unsupported / total > 0.20:
        return False

    return True
