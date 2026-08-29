"""Right-to-left text handling for Hebrew and Arabic replies.

Two bugs bite every WhatsApp bot that answers in Hebrew or Arabic, and both are
invisible until a real customer screenshots them:

1. A phone number, price range, URL or order id inside an RTL sentence renders
   with its segments in the wrong order, because the dashes, dots and slashes
   between digits are *neutral* characters and inherit the paragraph's
   right-to-left direction. `+972-52-624-7316` can display as `7316-624-52-972+`.
   Fix: wrap each such run in a LEFT-TO-RIGHT ISOLATE (U+2066 ... U+2069) so it
   is laid out left-to-right while staying in place inside the sentence.

2. A line that *starts* with a digit or a Latin word ("2026 ...", "WhatsApp ...")
   is guessed as a left-to-right paragraph by the first-strong-character rule, so
   the whole Hebrew or Arabic line flips its alignment. Fix: prefix the line with
   an invisible RIGHT-TO-LEFT MARK (U+200F).

Both fixes are pure text - no font, no client setting, nothing to install.
Every range below is written as an escape on purpose: the literal characters are
invisible or bidi-flipping in an editor, which is how these regexes get broken.
"""

from __future__ import annotations

import re

# Unicode bidirectional control characters used below.
LRI = "\u2066"  # LEFT-TO-RIGHT ISOLATE
PDI = "\u2069"  # POP DIRECTIONAL ISOLATE
RLM = "\u200F"  # RIGHT-TO-LEFT MARK

RTL_LANGUAGES = ("he", "ar")

# Hebrew block + Hebrew presentation forms.
_HEBREW = re.compile(r"[\u0590-\u05FF\uFB1D-\uFB4F]")
# Arabic, Arabic Supplement, Arabic Extended-A, and the presentation forms.
_ARABIC = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)
_LATIN = re.compile(r"[A-Za-z]")

# Any character that decides a paragraph's direction on its own (a "strong" RTL
# character). Used to tell whether a line already starts right-to-left.
_STRONG_RTL = re.compile(
    r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]"
)

# One alternation, matched left to right, so a URL is never re-chewed by the
# number branch. Order matters: longest / most specific pattern first.
#   1. http(s) URL   2. bare www. host   3. e-mail address
#   4. a number-like run: a digit, then digits and the usual separators, a digit
#
# Two deliberate choices in that last branch:
#   * The separator class spells out space and tab instead of using \s, because
#     \s also matches the newline. A run allowed to cross a line break would put
#     the opening isolate on one line and the closing one on the next - and the
#     RTL mark below is applied line by line, so the pair would never balance.
#   * The colon and the en/em dash are in the class on purpose. "09:00-18:00" is
#     the classic failure: two number runs with a neutral between them, which an
#     RTL paragraph reorders into "18:00-09:00" and shows closing time first.
_LTR_ISLAND = re.compile(
    r"(https?://[^\s]+"
    r"|www\.[^\s]+"
    r"|[^\s@]+@[^\s@]+\.[A-Za-z]{2,}"
    r"|\+?\d[\d:\u2013\u2014()./ \t-]{3,}\d)"
)


def detect_language(text: str) -> str:
    """Return 'he', 'ar' or 'en' from the script the customer actually used.

    Counting characters rather than stopping at the first hit keeps a single
    Latin brand name inside a Hebrew sentence from switching the whole reply to
    English. English is the fallback when nothing is recognised (digits only,
    emoji only, an empty body).
    """
    if not text:
        return "en"
    scores = {
        "he": len(_HEBREW.findall(text)),
        "ar": len(_ARABIC.findall(text)),
        "en": len(_LATIN.findall(text)),
    }
    best = max(scores, key=lambda key: scores[key])
    return best if scores[best] > 0 else "en"


def is_rtl(language: str) -> bool:
    return (language or "").lower() in RTL_LANGUAGES


def isolate_ltr_runs(text: str) -> str:
    """Wrap phone numbers, URLs and e-mail addresses in LTR isolates."""
    if not text:
        return text
    # Never nest isolates: a caller may hand us text that was already prepared.
    if LRI in text:
        return text
    return _LTR_ISLAND.sub(lambda m: LRI + m.group(1) + PDI, text)


def force_rtl_paragraphs(text: str) -> str:
    """Prefix every line that does not already begin with a strong RTL character
    with an invisible RTL mark, so the line is laid out right-to-left."""
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if not stripped or line.startswith(RLM):
            out.append(line)
            continue
        if _STRONG_RTL.match(stripped[0]):
            out.append(line)
        else:
            out.append(RLM + line)
    return "\n".join(out)


def prepare_outbound(text: str, language: str) -> str:
    """The single call to make on every reply before it is sent.

    Left-to-right languages are returned untouched, so English replies never
    carry invisible control characters that would show up in logs and tests.
    """
    if not text:
        return text
    if not is_rtl(language):
        return text
    return force_rtl_paragraphs(isolate_ltr_runs(text))
