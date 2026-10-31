"""Exact (rule, line) scoring on a small authored, non-independent fixture set."""
import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import time

from copilot.review import review_code

ROOT = Path(__file__).parent


def main():
    cases = json.loads((ROOT / 'evaluation/cases.json').read_text())
    rows = []
    tp = fp = fn = 0
    for case in cases:
        start = time.perf_counter()
        result = review_code(case['code'])
        elapsed = time.perf_counter() - start
        predicted = {(f.rule, f.line) for f in result.findings}
        expected = {tuple(v) for v in case['expected']}
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        rows.append({'id': case['id'], 'seconds': elapsed, 'expected': sorted(expected),
                     'predicted': sorted(predicted), 'status': result.status})
    output = {'dataset': '12 hand-authored synthetic cases; no training; no holdout',
              'matching': 'exact unique (rule ID, line); all returned rules counted',
              'llm': 'not evaluated; no API key required or used',
              'python': platform.python_version(), 'platform': platform.platform(),
              'versions': {n: importlib.metadata.version(n) for n in ['ruff', 'bandit', 'streamlit']},
              'tp': tp, 'fp': fp, 'fn': fn,
              'precision': tp / (tp + fp) if tp + fp else None,
              'recall': tp / (tp + fn) if tp + fn else None,
              'median_seconds': statistics.median(r['seconds'] for r in rows), 'cases': rows}
    (ROOT / 'evaluation/results.json').write_text(json.dumps(output, indent=2))
    print(json.dumps({k: v for k, v in output.items() if k != 'cases'}, indent=2))


if __name__ == '__main__':
    main()
