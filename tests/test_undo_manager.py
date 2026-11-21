"""Comprehensive unit tests for Luna's thread-safe UndoManager and text diff engine."""

import threading
import time
import unittest

from undo_manager import (
    DiffSpan,
    TextDiff,
    UndoManager,
    UndoRecord,
    clear_history,
    compute_text_diff,
    get_last_undo,
    get_undo_manager,
    peek_last,
    record_replacement,
)


class TextDiffTests(unittest.TestCase):
    def test_no_changes(self):
        diff = compute_text_diff("Hello world", "Hello world")
        self.assertEqual(diff.words_added, 0)
        self.assertEqual(diff.words_removed, 0)
        self.assertEqual(diff.summary, "No changes")
        self.assertEqual(len(diff.tokens_added), 0)
        self.assertEqual(len(diff.tokens_removed), 0)
        self.assertEqual(diff.net_word_delta, 0)
        self.assertEqual(diff.net_char_delta, 0)

    def test_word_insertions(self):
        diff = compute_text_diff("Hello world", "Hello beautiful brave world")
        self.assertEqual(diff.words_added, 2)
        self.assertEqual(diff.words_removed, 0)
        self.assertEqual(diff.summary, "+2 words")
        self.assertEqual(diff.tokens_added, ["beautiful", "brave"])
        self.assertEqual(diff.tokens_removed, [])
        self.assertEqual(diff.net_word_delta, 2)

    def test_word_deletions(self):
        diff = compute_text_diff("The quick brown fox jumps", "The fox jumps")
        self.assertEqual(diff.words_added, 0)
        self.assertEqual(diff.words_removed, 2)
        self.assertEqual(diff.summary, "-2 words")
        self.assertEqual(diff.tokens_removed, ["quick", "brown"])
        self.assertEqual(diff.net_word_delta, -2)

    def test_word_replacements(self):
        diff = compute_text_diff("its gong fine", "It's going well")
        self.assertGreater(diff.words_added, 0)
        self.assertGreater(diff.words_removed, 0)
        self.assertIn("/", diff.summary)
        self.assertIn("words", diff.summary)

    def test_spans_and_formatting(self):
        diff = compute_text_diff("first line\nsecond line", "first line\nthird line")
        self.assertTrue(any(span.tag == 'delete' for span in diff.spans))
        self.assertTrue(any(span.tag == 'insert' for span in diff.spans))
        self.assertTrue(any(span.tag == 'equal' for span in diff.spans))

    def test_edge_cases(self):
        # Empty string cases
        empty_diff = compute_text_diff("", "")
        self.assertEqual(empty_diff.summary, "No changes")

        diff_from_empty = compute_text_diff("", "New text")
        self.assertEqual(diff_from_empty.words_added, 2)
        self.assertEqual(diff_from_empty.words_removed, 0)

        diff_to_empty = compute_text_diff("Old text", "")
        self.assertEqual(diff_to_empty.words_added, 0)
        self.assertEqual(diff_to_empty.words_removed, 2)


class UndoRecordTests(unittest.TestCase):
    def test_record_properties_and_unpacking(self):
        t0 = time.time()
        record = UndoRecord(
            timestamp=t0,
            target_pid=1234,
            original_text="original text here",
            refined_text="refined text here",
            mode_id=2,
        )
        self.assertEqual(record.timestamp, t0)
        self.assertEqual(record.target_pid, 1234)
        self.assertEqual(record.original_text, "original text here")
        self.assertEqual(record.refined_text, "refined text here")
        self.assertEqual(record.mode_id, 2)
        self.assertIsInstance(record.diff, TextDiff)

        # 5-tuple unpacking support
        t, pid, orig, ref, mode = record
        self.assertEqual(t, t0)
        self.assertEqual(pid, 1234)
        self.assertEqual(orig, "original text here")
        self.assertEqual(ref, "refined text here")
        self.assertEqual(mode, 2)

        # Indexing and length
        self.assertEqual(len(record), 5)
        self.assertEqual(record[0], t0)
        self.assertEqual(record[1], 1234)
        self.assertEqual(record[2], "original text here")
        self.assertEqual(record[3], "refined text here")
        self.assertEqual(record[4], 2)


class UndoManagerTests(unittest.TestCase):
    def setUp(self):
        UndoManager.reset_instance()
        self.manager = UndoManager.get_instance()

    def tearDown(self):
        UndoManager.reset_instance()

    def test_singleton_behavior(self):
        m1 = UndoManager.get_instance()
        m2 = get_undo_manager()
        m3 = UndoManager()
        self.assertIs(m1, m2)
        self.assertIs(m1, m3)

    def test_basic_record_and_undo_lifo(self):
        record_replacement(100, "hello", "Hello.", mode_id=0)
        record_replacement(100, "world", "World!", mode_id=1)

        self.assertEqual(self.manager.count(), 2)

        # Peek without popping
        peeked = peek_last(100)
        self.assertIsNotNone(peeked)
        self.assertEqual(peeked.original_text, "world")
        self.assertEqual(self.manager.count(), 2)

        # First undo pops "world"
        undo1 = get_last_undo(100)
        self.assertIsNotNone(undo1)
        self.assertEqual(undo1.original_text, "world")
        self.assertEqual(undo1.refined_text, "World!")
        self.assertEqual(self.manager.count(), 1)

        # Second undo pops "hello"
        undo2 = get_last_undo(100)
        self.assertIsNotNone(undo2)
        self.assertEqual(undo2.original_text, "hello")
        self.assertEqual(self.manager.count(), 0)

        # Third undo returns None
        undo3 = get_last_undo(100)
        self.assertIsNone(undo3)

    def test_multi_app_isolation(self):
        """Ensure replacements in Notepad (PID 101) and VS Code (PID 202) are isolated."""
        pid_notepad = 101
        pid_vscode = 202

        record_replacement(pid_notepad, "notepad note 1", "Notepad Note 1.", mode_id=0)
        record_replacement(pid_vscode, "code comment 1", "Code Comment 1.", mode_id=2)
        record_replacement(pid_notepad, "notepad note 2", "Notepad Note 2.", mode_id=1)

        self.assertEqual(self.manager.count(pid_notepad), 2)
        self.assertEqual(self.manager.count(pid_vscode), 1)
        self.assertEqual(self.manager.count(), 3)

        # Undo in Notepad should pop note 2
        u1 = get_last_undo(pid_notepad)
        self.assertEqual(u1.original_text, "notepad note 2")
        self.assertEqual(self.manager.count(pid_notepad), 1)
        self.assertEqual(self.manager.count(pid_vscode), 1)

        # Undo in VS Code should pop code comment 1 without affecting notepad note 1
        u2 = get_last_undo(pid_vscode)
        self.assertEqual(u2.original_text, "code comment 1")
        self.assertEqual(self.manager.count(pid_vscode), 0)
        self.assertEqual(self.manager.count(pid_notepad), 1)

        # Remaining in Notepad
        u3 = get_last_undo(pid_notepad)
        self.assertEqual(u3.original_text, "notepad note 1")
        self.assertEqual(self.manager.count(), 0)

    def test_clear_isolated_and_global(self):
        record_replacement(10, "app1 text", "App1 Text.", mode_id=0)
        record_replacement(20, "app2 text", "App2 Text.", mode_id=0)

        # Clear only app 10
        clear_history(10)
        self.assertIsNone(get_last_undo(10))
        self.assertIsNotNone(get_last_undo(20))

        # Clear global
        record_replacement(10, "a", "A", mode_id=0)
        record_replacement(20, "b", "B", mode_id=0)
        clear_history(None)
        self.assertEqual(self.manager.count(), 0)

    def test_capacity_and_eviction(self):
        # Create a manager with max_history=3
        UndoManager.reset_instance()
        small_manager = UndoManager.get_instance(max_history=3)

        for i in range(5):
            small_manager.record_replacement(1, f"orig_{i}", f"ref_{i}", mode_id=0)

        self.assertEqual(small_manager.count(), 3)
        history = small_manager.get_history()
        # Oldest should have been evicted; remaining are 2, 3, 4
        self.assertEqual([r.original_text for r in history], ["orig_2", "orig_3", "orig_4"])

    def test_multithreaded_concurrency(self):
        """Verify thread safety under heavy concurrent replacement and undo calls."""
        errors = []

        def worker(pid):
            try:
                for i in range(25):
                    record_replacement(pid, f"orig_{pid}_{i}", f"ref_{pid}_{i}", mode_id=i % 6)
                    peek_last(pid)
                    time.sleep(0.001)
                    if i % 3 == 0:
                        get_last_undo(pid)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(pid,)) for pid in range(10, 15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent operations raised: {errors}")


if __name__ == '__main__':
    unittest.main()
