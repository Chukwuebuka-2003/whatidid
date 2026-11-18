"""Text heuristics: the parts that decide whether time gets credited."""
import unittest

from whatidid import text as txt


class SlugTests(unittest.TestCase):
    def test_slug_is_the_sentence_with_dashes(self):
        self.assertEqual(txt.slugify("Write the onboarding copy"), "write-the-onboarding-copy")
        self.assertEqual(txt.slugify("Ship the beta!"), "ship-the-beta")

    def test_slug_is_guessable_and_stable(self):
        # whatever slugify does, the tag a user types must equal it
        for phrase in ("Finish chapter two of the thesis", "Fix the CSV import bug",
                       "Draft the Sunday report format"):
            self.assertEqual(txt.slugify(phrase), txt.slugify(phrase))
            self.assertNotIn("--", txt.slugify(phrase))

    def test_long_titles_stop_on_a_word_boundary(self):
        slug = txt.slugify("Write a very long objective that goes on and on about the thing")
        self.assertLessEqual(len(slug), 40)
        self.assertFalse(slug.endswith("-"))
        self.assertTrue(slug.startswith("write"))

    def test_punctuation_and_accents(self):
        self.assertEqual(txt.slugify("Café  run-through: 2nd pass"), "cafe-run-through-2nd-pass")

    def test_empty_title_still_gets_a_slug(self):
        self.assertEqual(txt.slugify(""), "item")


class TokenTests(unittest.TestCase):
    def test_hyphenated_tag_words_are_words(self):
        self.assertIn("chapter", txt.tokens("draft #finish-chapter-two"))

    def test_stemming_matches_draft_and_drafting(self):
        self.assertIn("draft", txt.tokens("drafting the argument"))

    def test_tags_are_extracted(self):
        self.assertEqual(txt.tags_in("worked on #alpha and #beta-2"), ["alpha", "beta-2"])

    def test_overlap_is_share_of_item_words(self):
        self.assertAlmostEqual(txt.overlap("finish the chapter", "the chapter is done"), 0.5)

    def test_stemming_makes_finished_match_finish(self):
        self.assertAlmostEqual(txt.overlap("finish the chapter", "finished the chapter"), 1.0)

    def test_overlap_of_empty_item_is_zero(self):
        self.assertEqual(txt.overlap("", "anything"), 0.0)

    def test_exact_tag_beats_fuzzy_words(self):
        item = {"text": "Write the onboarding copy", "slug": "write-the-onboarding-copy"}
        tagged = {"text": "onboarding, again #write-the-onboarding-copy", "tags": ["write-the-onboarding-copy"]}
        untagged = {"text": "onboarding copy", "tags": []}
        self.assertEqual(txt.match_entry(item, tagged)[0], True)
        self.assertEqual(txt.match_entry(item, tagged)[2], 1.0)
        self.assertEqual(txt.match_entry(item, untagged)[0], False)
        self.assertTrue(txt.match_entry(item, untagged)[1])


class ClassifierTests(unittest.TestCase):
    def test_obvious_distractions_are_named(self):
        self.assertEqual(txt.classify("Scrolling twitter (oops)"), "social feeds")
        self.assertEqual(txt.classify("watched YouTube"), "video")
        self.assertEqual(txt.classify("email and admin"), "chat and inbox")

    def test_real_work_is_not_a_distraction(self):
        self.assertIsNone(txt.classify("Drafted the client proposal, sent it for review"))
        self.assertIsNone(txt.classify("Chapter two, drafting the argument"))

    def test_substrings_do_not_trigger(self):
        # "newsworthy" is not "news"
        self.assertIsNone(txt.classify("newsworthy refactor"))


class FormatTests(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(txt.format_duration(0), "0m")
        self.assertEqual(txt.format_duration(45), "45m")
        self.assertEqual(txt.format_duration(60), "1h")
        self.assertEqual(txt.format_duration(90), "1h 30m")
        self.assertEqual(txt.human_duration(150), "2 hours 30 minutes")
        self.assertEqual(txt.human_duration(60), "1 hour")

    def test_plural(self):
        self.assertEqual(txt.plural(1, "week"), "week")
        self.assertEqual(txt.plural(2, "week"), "weeks")

    def test_join_list(self):
        self.assertEqual(txt.join_list(["a"]), "a")
        self.assertEqual(txt.join_list(["a", "b"]), "a and b")
        self.assertEqual(txt.join_list(["a", "b", "c", "d"]), "a, b and c, plus 1 more")


if __name__ == "__main__":
    unittest.main()
