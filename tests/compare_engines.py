"""Interleave baseline/current live requests; report public examples and token usage.

Only --live calls OpenAI. Run with --live to perform twelve bounded public-text
calls (six old, six new), useful to reduce ordering bias in latency comparisons.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import Settings, api_key
from grammar_engine import GrammarEngine
from benchmark_round5 import summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('baseline_engine', ROOT/'round5-baseline'/'grammar_engine.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    engines = {'baseline':baseline.GrammarEngine(Settings(timeout_seconds=20),api_key()),
               'round5':GrammarEngine(Settings(timeout_seconds=20),api_key())}
    records = []
    samples = ('its going fine for me hby','idk what your talking about','i was thinking we could go tmrw')
    try:
        for index in range(6):
            order = ('baseline','round5') if index % 2 == 0 else ('round5','baseline')
            for name in order:
                engine = engines[name]
                capture = []
                create = engine.client.responses.create
                def record(**kw):
                    tick = perf_counter_ns()
                    result = create(**kw)
                    usage = result.usage
                    capture.append(dict(api_ms=(perf_counter_ns()-tick)/1e6,
                                        input_tokens=usage.input_tokens,output_tokens=usage.output_tokens,
                                        cached_tokens=usage.input_tokens_details.cached_tokens))
                    return result
                from unittest.mock import patch
                tick = perf_counter_ns()
                with patch.object(engine.client.responses,'create',record):
                    output = engine.correct(samples[index%3])
                records.append(dict(version=name,sample=index%3,engine_ms=(perf_counter_ns()-tick)/1e6,
                                    **capture[0]))
    finally:
        for engine in engines.values():
            engine.close()
    report = dict(scope='12 interleaved live requests: same three non-sensitive grammar examples, each twice per version; n=6 each, not a robust tail estimate.',
                  summary={name:{stage:summary([row[stage] for row in records if row['version']==name])
                                 for stage in ('engine_ms','api_ms')} for name in engines},records=records)
    (ROOT/'comparison-live-round5.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],indent=2))


if __name__ == '__main__':
    main()
