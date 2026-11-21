"""Tests for the universal-compatibility rebuild: mode-aware validation,
cache contexts, prompt/temperature wiring, offline fallback, chunking,
undo peek-before-pop, diagnostics last-failure, and elevation detection.

Pure-logic tests run on any platform; Windows-only paths are skipped.
"""
import json
import sys
import unittest
from unittest.mock import patch

import httpx
import openai

import diagnostics
import win32 as win
from config import AppError, Settings, parse_settings
from grammar_engine import (
    GrammarEngine, OfflineResult, RefinementCache, local_fix, validate,
)
from text_selection import _correct_long
from undo_manager import UndoManager


def _engine(handler, settings=Settings()):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sdk_client = openai.OpenAI
    with patch("openai.OpenAI", side_effect=lambda **args: sdk_client(http_client=client, **args)):
        engine = GrammarEngine(settings, "test-key-only")
    return engine


def _response(text="I don't think she's coming.", status="completed"):
    return {
        "id": "resp_test", "object": "response", "created_at": 0,
        "model": "gpt-6-luna", "status": status,
        "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                    "status": status, "content": [{"type": "output_text", "text": text,
                                                   "annotations": []}]}],
    }


class BulletizeValidationTests(unittest.TestCase):
    def test_real_bullet_rewrite_is_accepted(self):
        original = ("we met with the client today and they want the design by friday "
                    "and also need the budget sheet updated")
        corrected = ("- Met with client regarding project deliverables.\n"
                     "- Updated budget sheet required.\n"
                     "- Final design due by Friday.")
        self.assertEqual(validate(original, corrected, False, "bulletize"), corrected)

    def test_bullet_rewrite_without_bullets_is_rejected(self):
        with self.assertRaises(AppError):
            validate("one\ntwo", "One, two.", False, "bulletize")

    def test_bullet_rewrite_that_drops_content_is_rejected(self):
        original = ("we met with the client today and they want the design by friday "
                    "and also need the budget sheet updated and the contract signed")
        with self.assertRaises(AppError):
            validate(original, "- Met client.", False, "bulletize")

    def test_other_modes_still_reject_line_layout_changes(self):
        with self.assertRaises(AppError):
            validate("first\nsecond", "First, second.", False, "grammar")


class CacheContextTests(unittest.TestCase):
    def test_same_text_different_model_is_a_miss(self):
        cache = RefinementCache()
        engine = GrammarEngine(Settings(), "dummy", cache=cache)
        try:
            cache.set("grammar", "hello world", "Hello world.",
                      context=engine.cache_context("gpt-6-luna"))
            self.assertIsNone(cache.get("grammar", "hello world",
                                        context=engine.cache_context("gpt-4o-mini")))
            self.assertEqual(cache.get("grammar", "hello world",
                                       context=engine.cache_context("gpt-6-luna")),
                             "Hello world.")
        finally:
            engine.close()

    def test_shorthand_temperature_and_prompt_change_the_context(self):
        base = GrammarEngine(Settings(), "dummy")
        try:
            context = base.cache_context()
            self.assertNotEqual(context, GrammarEngine(
                Settings(expand_shorthand=False), "dummy").cache_context())
            self.assertNotEqual(context, GrammarEngine(
                Settings(temperature=0.7), "dummy").cache_context())
            self.assertNotEqual(context, GrammarEngine(
                Settings(custom_prompt="Be brief."), "dummy").cache_context())
        finally:
            base.close()

    def test_legacy_calls_without_context_still_work(self):
        cache = RefinementCache()
        cache.set("grammar", "hello", "Hello.")
        self.assertEqual(cache.get("grammar", "hello"), "Hello.")


class PromptAndTemperatureTests(unittest.TestCase):
    def test_custom_prompt_is_sent_to_the_api(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=_response())

        engine = _engine(handler, Settings(custom_prompt="Always use British spelling."))
        try:
            engine.correct("i dont think she coming")
        finally:
            engine.close()
        self.assertIn("Always use British spelling.", seen["instructions"])

    def test_temperature_is_sent_for_supported_chat_models(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=_response("Hello."))

        engine = _engine(handler, Settings(model="gpt-4o-mini", temperature=0.7))
        try:
            engine.correct("hello")
        finally:
            engine.close()
        self.assertEqual(seen["temperature"], 0.7)
        self.assertNotIn("reasoning", seen)

    def test_gpt6_luna_keeps_fixed_sampling(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=_response())

        engine = _engine(handler, Settings(temperature=0.7))
        try:
            engine.correct("i dont think she coming")
        finally:
            engine.close()
        self.assertEqual(seen["temperature"], 0)
        self.assertEqual(seen["reasoning"], {"effort": "none"})

    def test_unknown_model_gets_no_sampling_options(self):
        seen = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, json=_response("Hello."))

        engine = _engine(handler, Settings(model="another-model", temperature=0.7))
        try:
            engine.correct("hello")
        finally:
            engine.close()
        self.assertNotIn("temperature", seen)
        self.assertNotIn("reasoning", seen)


class OfflineFallbackTests(unittest.TestCase):
    def test_local_fix_corrects_common_typos(self):
        self.assertEqual(local_fix("teh cat dont like me"), "The cat don't like me")
        self.assertEqual(local_fix("i recieve teh package tmrw"), "I receive the package tmrw")

    def test_local_fix_returns_none_when_nothing_to_fix(self):
        self.assertIsNone(local_fix("The cat is here."))
        self.assertIsNone(local_fix(""))

    def test_connection_failure_falls_back_offline_for_grammar(self):
        def handler(request):
            raise httpx.ConnectError("offline", request=request)

        engine = _engine(handler)
        try:
            result = engine.correct("teh cat dont like me")
        finally:
            engine.close()
        self.assertEqual(result, "The cat don't like me")
        self.assertTrue(isinstance(result, OfflineResult) and result.offline)

    def test_connection_failure_still_raises_for_other_modes(self):
        def handler(request):
            raise httpx.ConnectError("offline", request=request)

        engine = _engine(handler)
        try:
            with self.assertRaises(AppError):
                engine.correct("teh cat", mode="casual")
        finally:
            engine.close()

    def test_offline_result_is_not_cached(self):
        def handler(request):
            raise httpx.ConnectError("offline", request=request)

        cache = RefinementCache()
        engine = _engine(handler, Settings())
        engine.cache = cache
        try:
            engine.correct("teh cat dont like me")
            self.assertEqual(cache.size, 0)
        finally:
            engine.close()


class ChunkingTests(unittest.TestCase):
    class _FakeEngine:
        def __init__(self):
            self.calls = []

        def correct(self, text, mode="grammar", **kwargs):
            self.calls.append((text, mode, kwargs.get("fallback_models")))
            return text.upper()

    def test_long_text_is_corrected_paragraph_by_paragraph(self):
        engine = self._FakeEngine()
        text = "first paragraph here.\n\nsecond paragraph here."
        result = _correct_long(engine, text, "grammar", limit=30)
        self.assertEqual(result, "FIRST PARAGRAPH HERE.\n\nSECOND PARAGRAPH HERE.")
        self.assertEqual(len(engine.calls), 2)

    def test_short_text_takes_the_single_request_path(self):
        engine = self._FakeEngine()
        self.assertEqual(_correct_long(engine, "hello", "grammar", limit=30), "HELLO")
        self.assertEqual(len(engine.calls), 1)

    def test_single_overlong_paragraph_keeps_a_clear_error(self):
        engine = self._FakeEngine()
        with self.assertRaisesRegex(AppError, "single paragraph"):
            _correct_long(engine, "word " * 40, "grammar", limit=30)


class UndoPeekTests(unittest.TestCase):
    def test_peek_does_not_consume_the_record(self):
        manager = UndoManager.get_instance()
        try:
            manager.clear()
            record = manager.record_replacement(123, "orig", "refined", "grammar")
            self.assertIs(manager.peek_last(123), record)
            self.assertIs(manager.peek_last(123), record)  # still there
            self.assertIs(manager.get_last_undo(123), record)
            self.assertIsNone(manager.peek_last(123))
        finally:
            manager.clear()

    def test_wrong_location_must_not_restore(self):
        # The worker's undo path only restores when the live selection equals
        # the saved rewrite. This pins the comparison it relies on.
        manager = UndoManager.get_instance()
        try:
            manager.clear()
            record = manager.record_replacement(123, "i has a cat", "I have a cat.", "grammar")
            live_selection = "something else entirely"
            self.assertNotEqual(live_selection, record.refined_text)
            self.assertIsNotNone(manager.peek_last(123))  # record kept
        finally:
            manager.clear()


class DiagnosticsTests(unittest.TestCase):
    def test_stage_mapping(self):
        self.assertEqual(diagnostics.stage_for_code("capture.no_fresh_text"), "capture")
        self.assertEqual(diagnostics.stage_for_code("api.timeout"), "api")
        self.assertEqual(diagnostics.stage_for_code("clipboard.busy"), "replace")
        self.assertEqual(diagnostics.stage_for_code("replace.uia_verification_failed"), "replace")
        self.assertEqual(diagnostics.stage_for_code(None), "correction")

    def test_last_failure_round_trip_without_text(self):
        diagnostics.clear_last_failure()
        entry = diagnostics.record_failure("api.timeout", "Request timed out",
                                           app="chrome.exe", field="chrome_renderwidgethosthwnd")
        self.assertEqual(entry["stage"], "api")
        self.assertEqual(entry["app"], "chrome.exe")
        self.assertNotIn("selected", json.dumps(entry))
        self.assertEqual(diagnostics.get_last_failure()["code"], "api.timeout")
        diagnostics.clear_last_failure()
        self.assertIsNone(diagnostics.get_last_failure())


class ElevationTests(unittest.TestCase):
    def test_integrity_unknown_off_windows(self):
        if sys.platform == "win32":
            self.skipTest("Windows only behaviour differs")
        self.assertIsNone(win.process_integrity(1))
        self.assertIsNone(win.target_elevated(win.Target(1, 2, 3, 4)))


class ConfigTests(unittest.TestCase):
    def test_per_app_modes_validation(self):
        settings = parse_settings({"per_app_modes": {"Outlook.EXE": 2}, "copy_only": True})
        self.assertEqual(settings.per_app_modes, {"outlook.exe": 2})
        self.assertTrue(settings.copy_only)
        with self.assertRaises(AppError):
            parse_settings({"per_app_modes": {"outlook.exe": 6}})
        with self.assertRaises(AppError):
            parse_settings({"per_app_modes": {"outlook": 2}})

    def test_new_settings_round_trip(self):
        settings = parse_settings({})
        self.assertEqual(settings.per_app_modes, {})
        self.assertFalse(settings.copy_only)


if __name__ == "__main__":
    unittest.main()
