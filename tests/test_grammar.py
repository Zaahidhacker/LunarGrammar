import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import openai

from config import AppError, Settings, api_key, load_settings, update_settings
from grammar_engine import CHAT_WORDS, SHORTHAND, GrammarEngine, validate


def response(text="I don't think she's coming.", status="completed", part_type="output_text"):
    part = {"type": part_type}
    if part_type == "refusal":
        part["refusal"] = text
    else:
        part["text"] = text
        part["annotations"] = []
    return {
        "id": "resp_test", "object": "response", "created_at": 0,
        "model": "gpt-6-luna", "status": status,
        "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                    "status": status, "content": [part]}],
    }


class OutputTests(unittest.TestCase):
    def test_unchanged_and_casual(self):
        self.assertEqual(validate("Already correct.", "Already correct."), "Already correct.")
        self.assertEqual(validate("bro what are u doing rn", "Bro, what are u doing rn?"),
                         "Bro, what are u doing rn?")

    def test_unicode_whitespace_and_paragraphs(self):
        original = "  i met Zoë at 3pm 😀\r\n\t\r\nça vas?  "
        corrected = "I met Zoë at 3 p.m. 😀\n\nÇa va ?"
        self.assertEqual(validate(original, corrected), "  I met Zoë at 3 p.m. 😀\r\n\t\r\nÇa va ?  ")

    def test_unsafe_results(self):
        pairs = [
            ("i went home", " "), ("hello", "Here is the corrected text: Hello."),
            ("hello", "Corrected text: Hello."), ("hello", '“Hello.”'),
            ("hello", "```\nHello.\n```"), ("hello", "Hello.\0"),
            ("hello", "Hello there, how are you doing today?"),
            ("i saw her today. this was in a small town nearby.", "I saw her."),
            ("first\nsecond", "First, second."), ("one\n\nthree", "One.\nTwo.\nThree."),
            ("i saw 33 birds", "I saw 34 birds."), ("hello 😀", "Hello. 😢"),
            ("visit https://example.com/a", "Visit https://example.com/b."),
        ]
        for original, corrected in pairs:
            with self.subTest(corrected=corrected), self.assertRaises(AppError):
                validate(original, corrected)

    def test_url_sentence_punctuation(self):
        self.assertEqual(validate("visit https://example.com/a", "Visit https://example.com/a."),
                         "Visit https://example.com/a.")


class ResponsesTests(unittest.TestCase):
    def engine(self, handler, settings=Settings()):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        sdk_client = openai.OpenAI
        with patch("openai.OpenAI", side_effect=lambda **args: sdk_client(http_client=client, **args)):
            engine = GrammarEngine(settings, "test-key-only")
        self.addCleanup(engine.close)
        return engine

    def test_request_uses_official_sdk_without_history(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
            body = json.loads(request.content)
            self.assertEqual(body["input"], "i dont think she coming")
            self.assertEqual(body["model"], "gpt-6-luna")
            self.assertIs(body["store"], False)
            self.assertEqual(body["temperature"], 0)
            self.assertEqual(body["reasoning"], {"effort": "none"})
            self.assertNotIn("previous_response_id", body)
            self.assertNotIn("conversation", body)
            return httpx.Response(200, json=response())

        self.assertEqual(self.engine(handler).correct("i dont think she coming"),
                         "I don't think she's coming.")

    def test_configured_model_omits_model_specific_options(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body["model"], "another-model")
            self.assertNotIn("reasoning", body)
            self.assertNotIn("temperature", body)
            return httpx.Response(200, json=response("Hello."))

        self.assertEqual(self.engine(handler, Settings(model="another-model")).correct("hello"), "Hello.")

    def test_chat_examples_are_sent_and_validated(self):
        pairs = {
            "its gong fine for me hby": "It's going fine for me. How about you?",
            "idk if im going tmrw": "I don't know if I'm going tomorrow.",
            "bro what are u doing rn": "Bro, what are you doing right now?",
            "i was gonna msg u but idk if ur free": "I was gonna message you, but I don't know if you're free.",
            "WYD RN": "What are you doing right now?",
        }

        def handler(request):
            body = json.loads(request.content)
            for word in CHAT_WORDS.findall(body['input']):
                self.assertIn(f'{word.lower()}={SHORTHAND[word.lower()]}', body['instructions'])
            self.assertNotIn('brb=be right back', body['instructions'])
            self.assertIn("Keep natural casual expressions such as bro and gonna", body["instructions"])
            return httpx.Response(200, json=response(pairs[body["input"]]))

        engine = self.engine(handler)
        for text, expected in pairs.items():
            with self.subTest(text=text):
                self.assertEqual(engine.correct(text), expected)

    def test_disabled_expansion_and_live_configuration(self):
        def handler(request):
            body = json.loads(request.content)
            self.assertNotIn("hby=how about you", body["instructions"])
            self.assertIn("Keep intentional chat abbreviations unexpanded", body["instructions"])
            return httpx.Response(200, json=response("Bro, wyd rn?"))

        engine = self.engine(handler)
        engine.configure(Settings(expand_shorthand=False))
        self.assertEqual(engine.correct("bro wyd rn"), "Bro, wyd rn?")

    def test_model_check_uses_metadata_endpoint_without_selected_text(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(str(request.url), "https://api.openai.com/v1/models/gpt-6-luna")
            self.assertEqual(request.content, b"")
            return httpx.Response(200, json={
                "id": "gpt-6-luna", "object": "model", "created": 0, "owned_by": "openai",
            })

        self.engine(handler).check_model()

    def test_errors_are_sanitized_and_attempted_once(self):
        cases = [
            (401, "invalid_api_key", "rejected OPENAI_API_KEY"),
            (403, "model_not_found", "project permissions"),
            (404, "model_not_found", "project permissions"),
            (429, "insufficient_quota", "quota is exhausted"),
            (429, "rate_limit_exceeded", "rate limiting"),
            (400, "invalid_request_error", "rejected the request"),
            (500, "server_error", "request failed"),
        ]
        for status, code, message in cases:
            with self.subTest(status=status, code=code):
                attempts = []

                def handler(request):
                    attempts.append(request)
                    return httpx.Response(status, json={"error": {"message": "private data", "code": code}})

                with self.assertRaisesRegex(AppError, message) as caught:
                    self.engine(handler).correct("hello")
                self.assertNotIn("private data", str(caught.exception))
                self.assertEqual(len(attempts), 1)

    def test_timeout_and_connection_failures(self):
        for kind, message in [(httpx.ReadTimeout, "timed out"), (httpx.ConnectError, "connect to OpenAI")]:
            with self.subTest(kind=kind):
                def handler(request):
                    raise kind("private data", request=request)

                # "Hello." is already correct, so the offline fallback has
                # nothing to fix and the API error must still surface.
                with self.assertRaisesRegex(AppError, message):
                    self.engine(handler).correct("Hello.")

    def test_incomplete_empty_and_refused(self):
        for payload, message in [
            (response(status="incomplete"), "did not complete"),
            (response(""), "empty correction"),
            (response("refused", part_type="refusal"), "declined"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(AppError, message):
                self.engine(lambda _: httpx.Response(200, json=payload)).correct("hello")


class ConfigTests(unittest.TestCase):
    def test_requires_environment_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": " "}), self.assertRaisesRegex(AppError, "missing"):
            api_key()

    def test_configuration_and_model_override(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"LUNA_GRAMMAR_MODEL": "other"}):
            path = Path(folder) / "settings.json"
            path.write_text('{"excluded_apps":["Notepad.EXE"],"max_selection_chars":500}', encoding="utf-8")
            settings = load_settings(path)
            self.assertEqual(settings, Settings(model="other", excluded_apps=("notepad.exe",),
                                                max_selection_chars=500))
            path.write_text('{"timeout_seconds":true}', encoding="utf-8")
            with self.assertRaisesRegex(AppError, "timeout_seconds"):
                load_settings(path)

    def test_preferences_update_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"excluded_apps":["notepad.exe"],"max_selection_chars":900}', encoding="utf-8")
            update_settings({"feedback": False, "motion": "reduced", "appearance": "light"}, path)
            settings = load_settings(path)
            self.assertEqual(settings.excluded_apps, ("notepad.exe",))
            self.assertEqual(settings.max_selection_chars, 900)
            self.assertEqual((settings.feedback, settings.motion, settings.appearance), (False, "reduced", "light"))
