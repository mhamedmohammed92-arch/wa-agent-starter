"""Language detection and right-to-left output preparation."""

import unittest

from app.rtl import LRI, PDI, RLM, detect_language, prepare_outbound

HEBREW = "\u05E9\u05DC\u05D5\u05DD"          # shalom
ARABIC = "\u0645\u0631\u062D\u0628\u0627"    # marhaba


class DetectLanguageTest(unittest.TestCase):
    def test_hebrew(self):
        self.assertEqual(detect_language(HEBREW), "he")

    def test_arabic(self):
        self.assertEqual(detect_language(ARABIC), "ar")

    def test_english(self):
        self.assertEqual(detect_language("what are your hours?"), "en")

    def test_one_latin_word_does_not_flip_a_hebrew_sentence(self):
        self.assertEqual(detect_language(HEBREW + " WhatsApp " + HEBREW), "he")

    def test_no_script_at_all_falls_back_to_english(self):
        self.assertEqual(detect_language("2026"), "en")
        self.assertEqual(detect_language(""), "en")


class PrepareOutboundTest(unittest.TestCase):
    def test_phone_number_is_wrapped_in_an_ltr_isolate(self):
        out = prepare_outbound(HEBREW + " +972-4-000-0000", "he")
        self.assertIn(LRI + "+972-4-000-0000" + PDI, out)

    def test_url_is_wrapped_in_an_ltr_isolate(self):
        out = prepare_outbound(ARABIC + " https://example.com/prices", "ar")
        self.assertIn(LRI + "https://example.com/prices" + PDI, out)

    def test_line_starting_with_a_digit_gets_an_rtl_mark(self):
        out = prepare_outbound("2026 " + HEBREW, "he")
        self.assertTrue(out.startswith(RLM))

    def test_line_already_starting_rtl_is_left_alone(self):
        out = prepare_outbound(HEBREW, "he")
        self.assertEqual(out, HEBREW)

    def test_english_is_returned_untouched(self):
        text = "Call +972-4-000-0000 or visit https://example.com"
        self.assertEqual(prepare_outbound(text, "en"), text)

    def test_running_twice_does_not_nest_isolates(self):
        once = prepare_outbound(HEBREW + " +972-4-000-0000", "he")
        twice = prepare_outbound(once, "he")
        self.assertEqual(once, twice)

    def test_time_range_is_isolated(self):
        # Without this, an RTL paragraph reorders the two halves and shows the
        # closing time first: "18:00-09:00".
        out = prepare_outbound(HEBREW + " 09:00-18:00", "he")
        self.assertIn(LRI + "09:00-18:00" + PDI, out)

    def test_isolates_never_span_a_line_break(self):
        # An isolate opened on one line and closed on the next never balances,
        # because the RTL mark is applied per line.
        out = prepare_outbound("2026\n2027 " + HEBREW, "he")
        for line in out.split("\n"):
            self.assertEqual(line.count(LRI), line.count(PDI))

    def test_every_line_is_handled_not_only_the_first(self):
        out = prepare_outbound(HEBREW + "\n120 ILS", "he")
        self.assertEqual(out.split("\n")[1][0], RLM)


if __name__ == "__main__":
    unittest.main()
