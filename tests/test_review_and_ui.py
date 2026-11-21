"""Review-before-apply, pill review state, vector bolt, ellipsizing and the
honest sound toggle. Pure-logic tests; they run on any platform."""
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import Settings
from pill_art import Motion, ellipsize, font, render
from text_selection import Trigger, correct_selection
from undo_manager import peek_last


class _FakeGuard:
    def check(self):
        pass


class _FakeSelection:
    def __init__(self, text):
        self.text = text
        self.guard = _FakeGuard()
        self.replaced = []

    def replace_with_keyboard(self, text, clipboard, automation=None, limit=6000):
        self.replaced.append(text)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        # Unique pid per test: the undo manager is a process-wide singleton,
        # so records from an earlier test must not leak into the next one.
        self.pid = 4242 + (id(self) % 10000)
        self.selection = _FakeSelection("i went home")
        self.capture = patch("text_selection.capture", return_value=self.selection).start()
        self.addCleanup(patch.stopall)
        self.engine = Mock()
        self.engine.correct.return_value = "I went home."
        self.clipboard = Mock()
        self.trigger = Trigger(SimpleNamespace(pid=self.pid, window=1, focus=2), 0)
        self.stop = Event()

    def run_flow(self, settings=Settings(), review_callback=None):
        return correct_selection(
            self.trigger, lambda: 0, self.stop, settings, None,
            self.clipboard, self.engine, review_callback=review_callback,
        )

    def test_apply_replaces_and_records_undo(self):
        result = self.run_flow(review_callback=lambda *args: True)
        self.assertEqual(result, "success")
        self.assertEqual(self.selection.replaced, ["I went home."])
        self.assertIsNotNone(peek_last(self.pid))

    def test_discard_replaces_nothing_and_records_no_undo(self):
        result = self.run_flow(review_callback=lambda *args: False)
        self.assertEqual(result, "discarded")
        self.assertEqual(self.selection.replaced, [])
        self.assertIsNone(peek_last(self.pid))

    def test_no_decision_applies_instead_of_stranding_the_correction(self):
        result = self.run_flow(review_callback=lambda *args: None)
        self.assertEqual(result, "success")
        self.assertEqual(self.selection.replaced, ["I went home."])

    def test_review_callback_receives_corrected_text_and_diff(self):
        seen = []

        def callback(corrected, original, diff):
            seen.append((corrected, original))
            return True

        self.run_flow(review_callback=callback)
        self.assertEqual(seen, [("I went home.", "i went home")])

    def test_copy_only_mode_never_asks_for_review(self):
        calls = []
        settings = Settings(copy_only=True)
        result = self.run_flow(settings=settings, review_callback=lambda *a: calls.append(a) or True)
        self.assertEqual(result, "copied")
        self.assertEqual(calls, [])
        self.clipboard.stage_text.assert_called_once_with("I went home.")


class PillReviewTests(unittest.TestCase):
    def test_review_pill_stays_for_the_decision_window_then_hides(self):
        motion = Motion()
        motion.begin(0, "Refining…")
        motion.finish("review", "I went home.", 1, diff_badge="+2 words")
        frame = motion.sample(6)
        self.assertIsNotNone(frame)
        self.assertTrue(frame.review)
        self.assertEqual(frame.label, "I went home.")
        self.assertIsNone(motion.sample(32))

    def test_review_pill_is_wider_than_a_plain_result_pill(self):
        plain = Motion()
        plain.begin(0, "Refining…")
        plain.finish("success", "I went home.", 1)
        review = Motion()
        review.begin(0, "Refining…")
        review.finish("review", "I went home.", 1, diff_badge="+2 words")
        self.assertGreater(review.sample(1.4).width, plain.sample(1.4).width)

    def test_review_pill_renders_with_apply_and_discard_buttons(self):
        motion = Motion()
        motion.begin(0, "Refining…")
        motion.finish("review", "I went home.", 1, diff_badge="+2 words")
        frame = motion.sample(1.4)
        image = render(frame, 96, "dark")
        self.assertEqual(image.size, (round(frame.width), 54))

    def test_long_result_label_is_ellipsized_and_width_is_clamped(self):
        motion = Motion()
        motion.begin(0, "Refining…")
        long_label = "Something went wrong and the message keeps going on and on and on and on"
        motion.finish("error", long_label, 1)
        frame = motion.sample(1.4)
        self.assertLessEqual(frame.width, 420)
        self.assertTrue(frame.label.endswith("…"))

    def test_ellipsize_keeps_short_text_and_truncates_long_text(self):
        f = font(13, "Medium")
        self.assertEqual(ellipsize("Short", f, 200), "Short")
        truncated = ellipsize("A very long sentence that will not fit", f, 100)
        self.assertTrue(truncated.endswith("…"))
        self.assertLessEqual(f.getlength(truncated), 100)

    def test_cached_badge_renders_without_the_emoji_glyph(self):
        motion = Motion()
        motion.begin(0, "Refining…")
        motion.finish("success", "Refined", 1, cached=True)
        frame = motion.sample(1.4)
        self.assertTrue(frame.cached)
        render(frame, 96, "dark")  # must not raise on the vector bolt


class SoundTests(unittest.TestCase):
    def test_chime_is_a_no_op_off_windows(self):
        import overlay

        pill = object.__new__(overlay.Overlay)
        pill._chime("success", Settings(sound_enabled=True))
        pill._chime("error", Settings(sound_enabled=True))
        pill._chime("success", Settings(sound_enabled=False))
        pill._chime("success", None)


if __name__ == "__main__":
    unittest.main()
