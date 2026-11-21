"""Deterministic request/validation integration contracts, not live model scores."""
from collections import Counter
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
import openai
from config import AppError, Settings
from correction_modes import MODES
from grammar_engine import GrammarEngine, validate
from test_grammar import response

EXAMPLES = json.loads(Path(__file__).with_name('quality_examples.json').read_text(encoding='utf-8'))


class QualityModesTests(unittest.TestCase):
    def test_48_examples_use_exactly_one_shared_request_each(self):
        baseline_modes = ('grammar', 'professional_1', 'professional_2', 'professional_3')
        self.assertEqual(Counter(case[0] for case in EXAMPLES), {name:12 for name in baseline_modes})
        sdk = openai.OpenAI
        calls = []
        expected = iter(EXAMPLES)
        def handle(request):
            mode, original, corrected = next(expected)
            body = json.loads(request.content)
            calls.append(body)
            self.assertEqual(body['input'], original)
            self.assertIn(MODES[mode].instructions, body['instructions'])
            self.assertNotIn('previous_response_id', body)
            self.assertFalse(body['store'])
            return httpx.Response(200, json=response(corrected))
        client = httpx.Client(transport=httpx.MockTransport(handle))
        with patch('openai.OpenAI', side_effect=lambda **kw: sdk(http_client=client, **kw)):
            engine = GrammarEngine(Settings(), 'test-key-only')
        try:
            for mode, original, corrected in EXAMPLES:
                with self.subTest(mode=mode, original=original):
                    self.assertEqual(engine.correct(original, mode), corrected)
        finally:
            engine.close()
        self.assertEqual(len(calls), 48)

    def test_all_modes_reject_changed_facts_and_unsolicited_markup(self):
        for mode in MODES:
            for before, after in [('Ravi needs 2 files 🙂', 'Ravi needs 3 files 🙂.'),
                                  ('hello 😀', 'Hello. 🙃'), ('hello', '**Hello.**'),
                                  ('hello', 'Here is the revised text: Hello.'),
                                  ('one\ntwo', 'One, two.'), ('hello', 'Hello.\x00'),
                                  ('https://example.com/a', 'https://example.com/b')]:
                with self.subTest(mode=mode, after=after), self.assertRaises(AppError):
                    validate(before, after, True, mode)

    def test_grammar_limits_remain_stricter_than_professionalism(self):
        before, after = EXAMPLES[36][1:]
        with self.assertRaises(AppError):
            validate(before, after, True)
        self.assertEqual(validate(before, after, True, 'professional_3'), after)

    def test_unknown_mode_fails_locally(self):
        with self.assertRaisesRegex(AppError, 'Unknown'):
            validate('hello', 'Hello.', mode='unexpected')


if __name__ == '__main__':
    unittest.main()
