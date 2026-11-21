"""Read-only function profiler for baseline/current native fixtures.

Run from the workspace: profile_stages.py --source DIR --output FILE [--clipboard].
The source directory can be the preserved baseline. Timings are inclusive.
"""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from functools import wraps
import json
from pathlib import Path
import sys
from time import perf_counter_ns
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', default='.')
parser.add_argument('--output', required=True)
parser.add_argument('--clipboard', action='store_true')
args = parser.parse_args()
source = Path(args.source).resolve()
sys.path.insert(0, str(source))
sys.path.insert(0, str(source / 'tests'))
import statistics
def summary(values):
    ordered = sorted(values)
    def p(fraction):
        index = (len(ordered)-1)*fraction
        low = int(index)
        return round(ordered[low]+(ordered[min(low+1,len(ordered)-1)]-ordered[low])*(index-low), 4)
    return dict(n=len(values), median_ms=round(statistics.median(values),4),p90_ms=p(.9),p95_ms=p(.95))
import clipboard_manager as cm
import text_selection as ts
import grammar_engine as ge


def main():
    import windows_clipboard_integration as fixture
    samples = defaultdict(list)
    def wrap(label, function):
        @wraps(function)
        def call(*a, **kw):
            tick = perf_counter_ns()
            try:
                return function(*a, **kw)
            finally:
                samples[label].append((perf_counter_ns() - tick) / 1e6)
        return call
    with ExitStack() as stack:
        for obj, name, label in ((cm,'snapshot','clipboard_snapshot'),(cm,'restore','clipboard_restore'),
                                 (cm.Clipboard,'copy','clipboard_copy'),(cm.Clipboard,'paste','paste_and_restore')):
            stack.enter_context(patch.object(obj,name,wrap(label,getattr(obj,name))))
        fixture.run(args.clipboard)
    result = {'source':source.name, 'timings':{key:summary(value) for key,value in samples.items()},
              'scope':'Real scratch Win32 clipboard, simulated editor dispatch; times inclusive. Cross-process delays may include Windows clipboard observers.'}
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
