"""Small offline dataset evaluation. References are loaded only after generation."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import statistics
from copilot.ai import add_ai_review
from copilot.config import local_credentials
from copilot.review import review_code


def token_f1(predicted, reference):
    p = Counter(re.findall(r"\w+", predicted.lower()))
    r = Counter(re.findall(r"\w+", reference.lower()))
    overlap = sum((p & r).values())
    precision = overlap / sum(p.values()) if p else 0
    recall = overlap / sum(r.values()) if r else 0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0


def evaluate(directory: Path, kind: str, with_ai=False):
    inputs = [
        json.loads(line)
        for line in (directory / "inputs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    if len(inputs) > 10:
        raise ValueError("Small evaluation accepts at most 10 inputs")
    outputs = []
    for case in inputs:
        review = review_code(case["code"], case["filename"])
        if with_ai:
            key, model = local_credentials()
            add_ai_review(review, case["code"], True, api_key=key, model=model)
        outputs.append((case, review))
    # References do not enter review_code, add_ai_review, or build_input.
    references = {
        str(row["id"]): row
        for row in (
            json.loads(line)
            for line in (directory / "references.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        )
    }
    rows = []
    for case, review in outputs:
        reference = references[str(case["id"])]
        row = {
            "id": case["id"],
            "provenance": case["provenance"],
            "findings": len(review.findings),
            "status": review.status,
            "static_seconds": review.elapsed_seconds,
            "ai_seconds": review.ai_latency_seconds,
            "usage": review.usage,
        }
        if kind == "bugsinpy":
            lines = set(reference["changed_lines"])
            row["changed_line_overlap"] = any(
                any(f.line_start <= n <= f.line_end for n in lines)
                for f in review.findings
            )
            row["known_bug_detection"] = (
                "not established; overlapping warnings may be unrelated"
            )
        else:
            generated = " ".join(
                f.explanation + " " + f.suggested_fix for f in review.findings
            )
            row["token_overlap_f1"] = token_f1(generated, reference["comment"])
            row["human_correctness"] = "not graded"
        rows.append(row)
    result = {
        "dataset": kind,
        "examples": len(rows),
        "mode": "hybrid" if with_ai else "static-only baseline",
        "raw_data_redistributed": False,
        "rows": rows,
        "median_static_seconds": statistics.median(r["static_seconds"] for r in rows),
        "fix_tests_reproduced": False,
        "cost_usd": None,
    }
    if kind == "bugsinpy":
        result["changed_line_overlap_cases"] = sum(
            r["changed_line_overlap"] for r in rows
        )
        result["warning"] = (
            "Overlap is a localization proxy, not known-bug recall. Extracted definitions lack module context."
        )
    else:
        result["mean_token_overlap_f1"] = statistics.mean(
            r["token_overlap_f1"] for r in rows
        )
        result["warning"] = (
            "Lexical overlap with a single human comment does not establish semantic review correctness."
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--kind", choices=["bugsinpy", "codereviewer"], required=True)
    parser.add_argument(
        "--with-ai",
        action="store_true",
        help="Explicit consent to send the prepared inputs to OpenAI",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.with_ai:
        if not local_credentials()[0]:
            parser.error(
                "Set OPENAI_API_KEY securely before requesting live AI evaluation"
            )
    result = evaluate(args.data, args.kind, args.with_ai)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
