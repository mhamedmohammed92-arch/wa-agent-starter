"""The single FAQ intent flow.

One JSON file (see `faq.json`) holds every intent: its keywords per language and
its answer per language. Change the file, restart, done - no Python edit needed.

Matching is keyword-based on purpose. It is deterministic, costs nothing, needs
no model key, and is honest about what it is: this is the free starter. The paid
kit replaces this module with embedding retrieval over your own documents, which
answers questions nobody wrote a keyword for.

Two details that keyword matching in Hebrew and Arabic gets wrong without care,
and that are handled in `normalize()`:

* One Arabic word has several accepted spellings. The same question arrives
  with a plain alef, an alef carrying hamza or madda, with a final ta-marbuta or
  a plain ha, with or without diacritics and tatweel. Left alone, each spelling
  is a different string and only one of them matches your keyword. Normalising
  those forms folds them onto one.
* Hebrew and Arabic both glue one-letter prefixes onto the front of a word (the
  conjunction, the article, the preposition), so a keyword has to match INSIDE a
  word, not only as a whole word. Latin is the opposite - "open" must not match
  "opener" - so Latin keywords are matched on word boundaries instead.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .rtl import detect_language

log = logging.getLogger("wa_agent.faq")

SUPPORTED_LANGUAGES = ("he", "ar", "en")

# --- text normalisation ---------------------------------------------------- #

# Arabic diacritics (harakat) and the superscript alef - decoration, never
# meaning, and customers type them inconsistently.
_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670]")
# Tatweel: a stretching character with no phonetic value.
_TATWEEL = "\u0640"
# Hebrew niqqud, cantillation, and the geresh/gershayim used in acronyms.
_HEBREW_MARKS = re.compile(r"[\u0591-\u05C7\u05F3\u05F4]")
# Bidi control characters a copy-paste can drag in.
_BIDI_CONTROLS = re.compile(r"[\u200E\u200F\u2066-\u2069\u202A-\u202E]")

_ARABIC_LETTER_MAP = {
    "\u0622": "\u0627",  # alef with madda    -> alef
    "\u0623": "\u0627",  # alef with hamza    -> alef
    "\u0625": "\u0627",  # alef with hamza    -> alef
    "\u0671": "\u0627",  # alef wasla         -> alef
    "\u0629": "\u0647",  # ta marbuta         -> ha
    "\u0649": "\u064A",  # alef maqsura       -> ya
    "\u0624": "\u0648",  # waw with hamza     -> waw
    "\u0626": "\u064A",  # ya with hamza      -> ya
}

# Arabic-Indic and extended Arabic-Indic digits -> 0-9, so a customer who types
# them is understood. Replies always use 0-9.
_DIGIT_MAP = {}
for _offset in range(10):
    _DIGIT_MAP[chr(0x0660 + _offset)] = str(_offset)
    _DIGIT_MAP[chr(0x06F0 + _offset)] = str(_offset)

_TRANSLATION = str.maketrans({**_ARABIC_LETTER_MAP, **_DIGIT_MAP, _TATWEEL: ""})

# Anything that is not a letter or a digit becomes a space, so punctuation can
# never hide a keyword.
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)

_ASCII_ONLY = re.compile(r"^[a-z0-9 ]+$")


def normalize(text: str) -> str:
    """Fold a message down to something keywords can be matched against."""
    if not text:
        return ""
    text = _BIDI_CONTROLS.sub("", text)
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _HEBREW_MARKS.sub("", text)
    text = text.translate(_TRANSLATION)
    text = _NON_WORD.sub(" ", text.lower())
    return " ".join(text.split())


def _keyword_hit(haystack: str, keyword: str) -> bool:
    """Substring for Hebrew/Arabic (attached prefixes), word boundary for Latin."""
    keyword = normalize(keyword)
    if not keyword:
        return False
    if _ASCII_ONLY.match(keyword):
        return re.search(r"\b" + re.escape(keyword) + r"\b", haystack) is not None
    return keyword in haystack


# --- the answer book ------------------------------------------------------- #


class FaqBook:
    """Intents and answers loaded from JSON, matched against one message."""

    def __init__(self, data: dict, default_language: str = "he") -> None:
        self.default_language = (
            default_language if default_language in SUPPORTED_LANGUAGES else "he"
        )
        self.intents = list(data.get("intents") or [])
        self.fallback = dict(data.get("fallback") or {})
        if not self.intents:
            log.warning("FAQ file has no intents - every message gets the fallback")

    @classmethod
    def load(cls, path: str | Path, default_language: str = "he") -> "FaqBook":
        path = Path(path)
        with path.open(encoding="utf-8") as handle:
            return cls(json.load(handle), default_language)

    def pick_language(self, text: str) -> str:
        language = detect_language(text)
        # detect_language falls back to English for a message with no script at
        # all (an emoji, "?"). Answer such a message in the configured default
        # instead, which is the language the business actually serves.
        if language == "en" and not re.search(r"[A-Za-z]", text or ""):
            return self.default_language
        return language

    def match(self, text: str) -> tuple[str | None, float]:
        """Return (intent id, score). Score 0 means nothing matched.

        Keywords from EVERY language are tried, not just the detected one: a
        Hebrew speaker who types "hours" still gets the opening times. The reply
        is then rendered in the language the customer wrote in.

        An intent may carry an optional "weight" (default 1.0). It exists for one
        real problem: "Hello, what are your opening hours?" hits both the
        greeting intent and the hours intent, and the greeting is the useless
        answer of the two. Giving greetings and thanks a weight below 1 makes any
        substantive intent win whenever both match, while a bare "Hello" still
        gets its greeting.
        """
        haystack = normalize(text)
        if not haystack:
            return None, 0.0

        best_id, best_score = None, 0.0
        for intent in self.intents:
            hits = 0
            for words in (intent.get("keywords") or {}).values():
                for keyword in words or []:
                    if _keyword_hit(haystack, keyword):
                        # Longer keywords are more specific: "opening hours"
                        # should beat a bare "hours" on another intent.
                        hits += len(normalize(keyword))
            if not hits:
                continue
            try:
                weight = float(intent.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            score = hits * weight
            if score > best_score:
                best_id, best_score = intent.get("id"), score
        return best_id, best_score

    def _text_for(self, block: dict, language: str) -> str:
        """The answer in the customer's language, degrading to a language that
        exists rather than to an empty message."""
        for candidate in (language, self.default_language, "en", "he", "ar"):
            value = (block or {}).get(candidate)
            if value:
                return value
        return next((v for v in (block or {}).values() if v), "")

    def fallback_text(self, language: str) -> str:
        """The "I did not understand" answer, used for message types that carry
        no text at all (audio, stickers, locations)."""
        return self._text_for(self.fallback, language)

    def answer(self, text: str) -> tuple[str, str, str | None]:
        """Return (reply_text, language, matched_intent_id)."""
        language = self.pick_language(text)
        intent_id, score = self.match(text)
        if not intent_id or score <= 0:
            return self._text_for(self.fallback, language), language, None
        intent = next(i for i in self.intents if i.get("id") == intent_id)
        return self._text_for(intent.get("reply") or {}, language), language, intent_id
