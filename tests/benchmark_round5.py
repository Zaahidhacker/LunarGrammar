"""Comparable baseline/current measurements; live calls use only public scratch text.

Run with --output PATH [--live]. No keys or document/response text is recorded.
Function timings are inclusive and must not be added together.
"""
import argparse
from collections import defaultdict
import ctypes as c
from functools import wraps
import json
from pathlib import Path
import statistics
import sys
from threading import Event
from time import perf_counter_ns
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import win32 as win
import grammar_engine as ge
import text_selection as ts
from config import Settings, api_key


def summary(values):
    ordered = sorted(values)
    def percentile(p):
        index = (len(ordered) - 1) * p
        lower = int(index)
        return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (index - lower)
    return dict(n=len(values), median_ms=round(statistics.median(values), 4),
                p90_ms=round(percentile(.90), 4), p95_ms=round(percentile(.95), 4))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    samples = defaultdict(list)
    def timed(name, function):
        @wraps(function)
        def run(*a, **kw):
            start = perf_counter_ns()
            try:
                return function(*a, **kw)
            finally:
                samples[name].append((perf_counter_ns() - start) / 1e6)
        return run
    root = win.create_window(0, 'Static', 'Luna benchmark', 0, 0, 0, 680, 240,
                             None, None, win.get_module(None), None)
    editor = win.create_window(0, 'Edit', '', 0x40000000 | 0x0004 | 0x0040 | 0x0080,
                               0, 0, 640, 200, root, None, win.get_module(None), None)
    if not root or not editor:
        raise c.WinError(c.get_last_error())
    import os
    target = win.Target(root, editor, 0, os.getpid())
    engine = Mock()
    engine.correct.return_value = 'I met Zoë 😀.\r\nShe has a Luna test.'
    text = 'i met Zoë 😀\r\nshe has a luna test'
    prefix, suffix = 'Before [', '] After'
    original = prefix + text + suffix
    start = len(prefix.encode('utf-16-le')) // 2
    end = start + len(text.encode('utf-16-le')) // 2
    clipboard = Mock()
    try:
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(win, 'current_target', return_value=target))
            stack.enter_context(patch.object(win, 'keys_down', return_value=False))
            stack.enter_context(patch.object(win, 'last_input', return_value=1))
            for obj, name, label in ((ts, 'capture', 'capture'), (ts.Selection, 'verify', 'target_verification'),
                                     (win, 'replace_native', 'replacement')):
                stack.enter_context(patch.object(obj, name, timed(label, getattr(obj, name))))
            for _ in range(100):
                value = c.create_unicode_buffer(original)
                win.send_window_message(editor, 0x000C, 0, c.addressof(value))
                win.send_window_message(editor, 0x00B1, start, end)
                tick = perf_counter_ns()
                assert ts.correct_selection(ts.Trigger(target, 0), lambda: 0, Event(), Settings(),
                                            None, clipboard, engine) == 'success'
                samples['native_pipeline_mock_ai'].append((perf_counter_ns() - tick) / 1e6)
                assert win.send_window_message(editor, 0x00C7)
            assert not clipboard.mock_calls
    finally:
        win.destroy_window(editor)
        win.destroy_window(root)

    import httpx
    import openai
    payload = {'id':'resp_bench','object':'response','created_at':0,'model':'gpt-6-luna',
               'status':'completed','output':[{'id':'msg_bench','type':'message','role':'assistant',
               'status':'completed','content':[{'type':'output_text','text':"It's going fine for me. How about you?",'annotations':[]}]}]}
    sdk = openai.OpenAI
    transport = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    with patch('openai.OpenAI', side_effect=lambda **kw: sdk(http_client=transport, **kw)):
        mock_engine = ge.GrammarEngine(Settings(), 'test-key-only')
    with patch.object(ge, 'validate', timed('output_validation', ge.validate)):
        for _ in range(100):
            tick = perf_counter_ns()
            mock_engine.correct('its going fine for me hby')
            samples['engine_mock_http'].append((perf_counter_ns() - tick) / 1e6)
    mock_engine.close()
    live = []
    if args.live:
        engine = ge.GrammarEngine(Settings(timeout_seconds=20), api_key())
        create = engine.client.responses.create
        def record(**kwargs):
            tick = perf_counter_ns()
            response = create(**kwargs)
            samples['live_api'].append((perf_counter_ns() - tick) / 1e6)
            usage = response.usage
            live.append(dict(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                             cached_tokens=usage.input_tokens_details.cached_tokens))
            return response
        try:
            with patch.object(engine.client.responses, 'create', record):
                for text in ('its going fine for me hby', 'idk what your talking about',
                             'i was thinking we could go tmrw'):
                    tick = perf_counter_ns()
                    engine.correct(text)
                    samples['live_engine'].append((perf_counter_ns() - tick) / 1e6)
        finally:
            engine.close()
    result = dict(scope='Windows native Edit: 100 mocked-AI corrections; SDK: 100 mock HTTP calls; optional live grammar: 3',
                  clipboard='Not used by this native Edit path; measured separately with guarded clipboard fixture',
                  timings={k:summary(v) for k,v in samples.items()}, live_usage=live)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
