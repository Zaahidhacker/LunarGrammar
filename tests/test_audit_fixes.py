"""Tests for the audit items fixed after test_universal_fixes.py was written:
phantom undo records, model fallback in the live path, specific validation
reasons, cache-singleton locking, the six-mode overlay count, and the
diagnostics double-count fix. Pure-logic tests; they run on any platform."""
import threading
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import openai

import diagnostics
import win32 as win
from config import AppError, Settings
from correction_modes import list_modes
from grammar_engine import GrammarEngine, RefinementCache
from text_selection import Trigger, _correct_once, correct_selection
from undo_manager import peek_last


def _engine(handler, settings=Settings()):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sdk_client = openai.OpenAI
    with patch("openai.OpenAI", side_effect=lambda **args: sdk_client(http_client=client, **args)):
        return GrammarEngine(settings, "test-key-only")


def _response(text, usage=None):
    body = {
        "id": "resp_test", "object": "response", "created_at": 0,
        "model": "gpt-6-luna", "status": "completed",
        "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                    "status": "completed", "content": [{"type": "output_text", "text": text,
                                                         "annotations": []}]}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


class _FakeGuard:
    def check(self):
        pass


class _FakeSelection:
    def __init__(self, text, fail_replace=False):
        self.text = text
        self.guard = _FakeGuard()
        self.replaced = []
        self.fail_replace = fail_replace

    def replace_with_keyboard(self, text, clipboard, automation=None, limit=6000):
        if self.fail_replace:
            raise AppError("Replace failed")
        self.replaced.append(text)


class PhantomUndoTests(unittest.TestCase):
    def test_failed_replace_leaves_no_phantom_undo_record(self):
        pid = 4242 + (id(self) % 10000)
        selection = _FakeSelection("i went home", fail_replace=True)
        with patch("text_selection.capture", return_value=selection):
            engine = Mock()
            engine.correct.return_value = "I went home."
            trigger = Trigger(SimpleNamespace(pid=pid, window=1, focus=2), 0)
            with self.assertRaises(AppError):
                correct_selection(trigger, lambda: 0, Event(), Settings(), None,
                                  Mock(), engine)
        self.assertIsNone(peek_last(pid))


class LivePathFallbackTests(unittest.TestCase):
    def test_correct_once_enables_model_fallback(self):
        engine = Mock()
        engine.correct.return_value = "I went home."
        _correct_once(engine, "i went home", "grammar")
        engine.correct.assert_called_once_with("i went home", fallback_models=True)


class ValidationSpecificityTests(unittest.TestCase):
    def test_url_changing_correction_keeps_its_reason(self):
        engine = _engine(lambda request: httpx.Response(
            200, json=_response("Visit https://example.org today")))
        with self.assertRaises(AppError) as caught:
            engine.correct("Visit https://example.com today")
        error = caught.exception
        self.assertEqual(error.code, "api.validation_failed")
        self.assertNotIn("Invalid correction", error.status)
        self.assertIn("URL", error.status)


class SingletonLockingTests(unittest.TestCase):
    def test_concurrent_get_instance_returns_one_object(self):
        RefinementCache._instance = None
        results = []

        def fetch():
            results.append(RefinementCache.get_instance())

        threads = [threading.Thread(target=fetch) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(set(map(id, results))), 1)


class OverlayModeCountTests(unittest.TestCase):
    def test_check_overlay_counts_six_canonical_modes(self):
        self.assertEqual(len(list_modes()), 6)


class DiagnosticsCountingTests(unittest.TestCase):
    def test_api_tokens_and_chars_are_counted_once(self):
        settings = Settings(cache_enabled=False)
        engine = _engine(
            lambda request: httpx.Response(
                200, json=_response("I went home.",
                                    usage={"input_tokens": 10, "output_tokens": 5,
                                           "total_tokens": 15})),
            settings=settings,
        )
        before = diagnostics._tracker.get_throughput_stats()
        engine.correct("i went home")
        after = diagnostics._tracker.get_throughput_stats()
        self.assertEqual(after["input_tokens"] - before["input_tokens"], 10)
        self.assertEqual(after["output_tokens"] - before["output_tokens"], 5)
        self.assertEqual(after["input_chars"] - before["input_chars"], len("i went home"))
        self.assertEqual(after["output_chars"] - before["output_chars"], len("I went home."))


if __name__ == "__main__":
    unittest.main()
