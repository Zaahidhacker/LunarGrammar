"""Opt-in live evaluation: four requests using one non-sensitive public example."""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter_ns
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from config import Settings, api_key
from grammar_engine import GrammarEngine
from correction_modes import MODES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',required=True,action='store_true')
    parser.parse_args()
    selected='hey can u send me the files when ur free'
    engine=GrammarEngine(Settings(timeout_seconds=20),api_key())
    rows=[]
    create=engine.client.responses.create
    usage=[]
    def record(**kw):
        response=create(**kw)
        usage.append(dict(input_tokens=response.usage.input_tokens,
                          output_tokens=response.usage.output_tokens,
                          cached_tokens=response.usage.input_tokens_details.cached_tokens))
        return response
    try:
        with patch.object(engine.client.responses,'create',record):
            for mode in MODES:
                tick=perf_counter_ns()
                output=engine.correct(selected,mode)
                rows.append(dict(mode=mode,input=selected,output=output,
                                 elapsed_ms=round((perf_counter_ns()-tick)/1e6,3),**usage[-1]))
    finally:
        engine.close()
    # Standard published GPT-6 Luna rates, checked 2026-11-12; invoice can differ.
    estimated_usd=sum((r['input_tokens']-r['cached_tokens'])*.10+r['cached_tokens']*.01+
                      r['output_tokens']*.50 for r in rows)/1e6
    report=dict(scope='Four actual GPT-6 Luna responses to public example text; not a broad linguistic evaluation.',
                estimated_standard_usd=estimated_usd,rows=rows)
    (ROOT/'live-mode-evaluation-round5.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
