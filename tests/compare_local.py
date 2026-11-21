"""Interleaved local timings on the same real hidden Edit control; no network."""
import ctypes as c
from collections import defaultdict
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import sys
from threading import Event
from time import perf_counter_ns
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmark_round5 import summary
import text_selection as current
import grammar_engine as ge
from config import Settings
import win32 as win


def archived(name):
    spec = importlib.util.spec_from_file_location(name+'_baseline',ROOT/'round5-baseline'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    baseline, old_engine = archived('text_selection'), archived('grammar_engine')
    samples = defaultdict(list)
    root = win.create_window(0,'Static','Luna paired benchmark',0,0,0,680,240,None,None,win.get_module(None),None)
    editor = win.create_window(0,'Edit','',0x40000000|0x0004|0x0040|0x0080,0,0,640,200,root,None,win.get_module(None),None)
    if not root or not editor:
        raise c.WinError(c.get_last_error())
    target = win.Target(root,editor,0,os.getpid())
    clipboard, engine = Mock(), Mock()
    engine.correct.return_value = 'I met Zoë 😀.'
    original = 'Before [i met Zoë 😀] After'
    start, end = 8, 20
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(win,'current_target',return_value=target))
            stack.enter_context(patch.object(win,'keys_down',return_value=False))
            stack.enter_context(patch.object(win,'last_input',return_value=1))
            for index in range(200):
                order = [('baseline',baseline),('round5',current)]
                if index%2:
                    order.reverse()
                for name,module in order:
                    value = c.create_unicode_buffer(original)
                    win.send_window_message(editor,0x000C,0,c.addressof(value))
                    win.send_window_message(editor,0x00B1,start,end)
                    tick=perf_counter_ns()
                    result=module.correct_selection(module.Trigger(target,0),lambda:0,Event(),Settings(),None,clipboard,engine)
                    samples[name+'.native_pipeline_mock_ai'].append((perf_counter_ns()-tick)/1e6)
                    assert result=='success'
                    assert win.send_window_message(editor,0x00C7)
            assert not clipboard.mock_calls
    finally:
        win.destroy_window(editor)
        win.destroy_window(root)
    for name,module in [('baseline',old_engine),('round5',ge)]:
        engine = object.__new__(module.GrammarEngine)
        import openai
        engine.sdk = openai
        engine.configure(Settings())
        engine.client = SimpleNamespace(responses=SimpleNamespace())
        def create(**_kw):
            samples[name+'.api_preparation'].append((perf_counter_ns()-tick)/1e6)
            return SimpleNamespace(status='completed',output=[],output_text="It's going fine for me. How about you?",usage=None)
        engine.client.responses.create = create
        for _ in range(1000):
            tick = perf_counter_ns()
            engine.correct('its going fine for me hby')
            samples[name+'.engine_mock_response'].append((perf_counter_ns()-tick)/1e6)
    result = {'scope':'200 interleaved real native Edit transactions per version (AI mocked); 1000 engine calls with immediate mocked responses. Excludes physical key hold and network.',
              'timings':{key:summary(value) for key,value in samples.items()}}
    (ROOT/'comparison-local-round5.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
