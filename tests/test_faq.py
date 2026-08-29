"""Intent matching over the shipped faq.json.

Test data is written as \\u escapes on purpose: Hebrew and Arabic literals flip
the direction of a source line in most editors, and a failure message printed on
a terminal without those fonts is unreadable. The translations are in the
comments.
"""

import unittest
from pathlib import Path

from app.faq import FaqBook, normalize

FAQ_PATH = Path(__file__).resolve().parent.parent / "faq.json"

# Hebrew: "what are your opening hours?"
HE_HOURS = "\u05DE\u05D4 \u05E9\u05E2\u05D5\u05EA \u05D4\u05E4\u05E2\u05D9\u05DC\u05D5\u05EA?"
# Hebrew: "hello, what are your opening hours?"
HE_GREET_AND_HOURS = "\u05E9\u05DC\u05D5\u05DD, \u05DE\u05D4 \u05E9\u05E2\u05D5\u05EA \u05D4\u05E4\u05E2\u05D9\u05DC\u05D5\u05EA?"
# Hebrew: "hello"
HE_GREETING = "\u05E9\u05DC\u05D5\u05DD"
# Arabic: "what are the prices?" spelled with alef-hamza
AR_PRICES_HAMZA = "\u0634\u0648 \u0627\u0644\u0623\u0633\u0639\u0627\u0631\u061F"
# Arabic: the same question spelled with a plain alef
AR_PRICES_PLAIN = "\u0634\u0648 \u0627\u0644\u0627\u0633\u0639\u0627\u0631\u061F"


class NormalizeTest(unittest.TestCase):
    def test_alef_spellings_collapse_to_one(self):
        self.assertEqual(normalize(AR_PRICES_HAMZA), normalize(AR_PRICES_PLAIN))

    def test_arabic_indic_digits_become_western_digits(self):
        self.assertEqual(normalize("\u0661\u0662\u0660"), "120")

    def test_punctuation_cannot_hide_a_keyword(self):
        self.assertEqual(normalize("Hours???"), "hours")


class MatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = FaqBook.load(FAQ_PATH, default_language="he")

    def test_hebrew_question_matches_hours_and_answers_in_hebrew(self):
        reply, language, intent = self.book.answer(HE_HOURS)
        self.assertEqual(intent, "hours")
        self.assertEqual(language, "he")
        self.assertTrue(reply)

    def test_a_real_question_beats_the_greeting_it_arrived_with(self):
        _, _, intent = self.book.answer(HE_GREET_AND_HOURS)
        self.assertEqual(intent, "hours")

    def test_a_bare_greeting_still_gets_the_greeting(self):
        _, _, intent = self.book.answer(HE_GREETING)
        self.assertEqual(intent, "greeting")

    def test_both_arabic_spellings_reach_the_same_intent(self):
        self.assertEqual(self.book.match(AR_PRICES_HAMZA)[0], "pricing")
        self.assertEqual(self.book.match(AR_PRICES_PLAIN)[0], "pricing")

    def test_arabic_question_is_answered_in_arabic(self):
        _, language, _ = self.book.answer(AR_PRICES_HAMZA)
        self.assertEqual(language, "ar")

    def test_english_keyword_works_for_a_hebrew_speaker(self):
        # Keywords from every language are tried, so this matches; the reply
        # language follows the script the customer actually typed.
        _, language, intent = self.book.answer("delivery?")
        self.assertEqual(intent, "delivery")
        self.assertEqual(language, "en")

    def test_unknown_question_gets_the_fallback(self):
        reply, language, intent = self.book.answer("zzz qqq wwww")
        self.assertIsNone(intent)
        self.assertEqual(language, "en")
        self.assertEqual(reply, self.book.fallback["en"])

    def test_message_with_no_script_uses_the_default_language(self):
        # An emoji-only message has no script to detect - answer in the language
        # the business configured, not in English by accident.
        _, language, _ = self.book.answer("\U0001F642")
        self.assertEqual(language, "he")

    def test_every_intent_has_all_three_languages(self):
        for intent in self.book.intents:
            for block in ("keywords", "reply"):
                with self.subTest(intent=intent["id"], block=block):
                    self.assertEqual(
                        set(intent[block]), {"he", "ar", "en"},
                        "an intent missing a language answers in the wrong one",
                    )


if __name__ == "__main__":
    unittest.main()
