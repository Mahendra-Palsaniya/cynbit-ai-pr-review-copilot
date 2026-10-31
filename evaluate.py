"""Exact canonical rule/line fixture metrics. Never feed labels to the review engine."""

import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import time
from copilot.review import review_code

ROOT = Path(__file__).parent
SEVERITY = {
    "F401": "low",
    "F821": "high",
    "MUTABLE_DEFAULT": "medium",
    "BARE_EXCEPT": "medium",
    "B110": "low",
    "B307": "medium",
    "B101": "low",
    "SYNTAX": "high",
    "EMPTY_INPUT_DIVISION": "medium",
}


def canonical(rule):
    return "BARE_EXCEPT" if rule == "E722" else rule


def metrics(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def main():
    cases = json.loads((ROOT / "evaluation/cases.json").read_text(encoding="utf-8"))
    rows = []
    tp = fp = fn = severity_correct = 0
    for case in cases:
        start = time.perf_counter()
        result = review_code(case["code"])
        elapsed = time.perf_counter() - start
        predicted = {(canonical(f.rule), f.line_start): f for f in result.findings}
        expected = {(canonical(rule), line) for rule, line in case["expected"]}
        keys = set(predicted)
        matched = keys & expected
        tp += len(matched)
        fp += len(keys - expected)
        fn += len(expected - keys)
        severity_correct += sum(
            predicted[key].severity == SEVERITY[key[0]] for key in matched
        )
        rows.append(
            {
                "id": case["id"],
                "seconds": elapsed,
                "expected": sorted(expected),
                "predicted": sorted(keys),
                "status": result.status,
                "false_positive": sorted(keys - expected),
                "false_negative": sorted(expected - keys),
            }
        )
    output = {
        "dataset": "12 hand-authored synthetic cases; no training or holdout",
        "unit": "Unique (canonical rule ID, line_start) finding per file; E722 and BARE_EXCEPT merged",
        "llm": "not evaluated by this script",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "versions": {
            n: importlib.metadata.version(n) for n in ["ruff", "bandit", "streamlit"]
        },
        "tp": tp,
        "fp": fp,
        "fn": fn,
        **metrics(tp, fp, fn),
        "severity_accuracy_on_matched_findings": severity_correct / tp if tp else None,
        "severity_reference": "Authored fixture triage labels; not a recognized severity benchmark",
        "line_localization": "Exact source line required for true-positive matching",
        "fix_success_rate": None,
        "fix_note": "No fixes executed; uploaded code is never executed",
        "api_latency_seconds": None,
        "cost_per_review_usd": None,
        "median_seconds": statistics.median(row["seconds"] for row in rows),
        "cases": rows,
    }
    (ROOT / "evaluation/results.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in output.items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    main()
