"""Inspect two SWE-bench Lite records without executing benchmark scripts or patches."""

import argparse
import hashlib
import json
from pathlib import Path


def split_rows(rows, output):
    inputs = [
        {k: row[k] for k in ["instance_id", "repo", "base_commit", "problem_statement"]}
        for row in rows
    ]
    references = [
        {k: row[k] for k in ["instance_id", "patch", "test_patch"]} for row in rows
    ]
    output.mkdir(parents=True, exist_ok=True)
    for name, values in [("inputs.jsonl", inputs), ("references.jsonl", references)]:
        (output / name).write_text(
            "\n".join(json.dumps(row) for row in values) + "\n", encoding="utf-8"
        )
    return [row["instance_id"] for row in rows]


def prepare_jsonl(path: Path, output: Path, limit=2):
    if path.stat().st_size > 1_000_000:
        raise ValueError("Use a small JSONL export under 1 MB")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ][:limit]
    return {
        "dataset": "SWE-bench Lite",
        "selected_ids": split_rows(rows, output),
        "status": "Issue/schema inspection only; no issue-resolution evaluation",
        "reference_leakage": "Gold and test patches separated from issue inputs",
    }


def prepare(parquet: Path, output: Path, limit=2):
    if parquet.stat().st_size > 10_000_000:
        raise ValueError("Expected the small Lite test parquet, at most 10 MB")
    import pyarrow.parquet as pq

    table = pq.read_table(parquet)
    if not {
        "instance_id",
        "repo",
        "base_commit",
        "problem_statement",
        "patch",
        "test_patch",
    } <= set(table.column_names):
        raise ValueError("Unexpected SWE-bench schema")
    rows = table.slice(0, limit).to_pylist()
    output.mkdir(parents=True, exist_ok=True)
    inputs = [
        {k: row[k] for k in ["instance_id", "repo", "base_commit", "problem_statement"]}
        for row in rows
    ]
    references = [
        {k: row[k] for k in ["instance_id", "patch", "test_patch"]} for row in rows
    ]
    for name, values in [("inputs.jsonl", inputs), ("references.jsonl", references)]:
        (output / name).write_text(
            "\n".join(json.dumps(row) for row in values) + "\n", encoding="utf-8"
        )
    return {
        "dataset": "SWE-bench Lite",
        "file_bytes": parquet.stat().st_size,
        "sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
        "available_test_rows": table.num_rows,
        "selected_ids": [row["instance_id"] for row in rows],
        "columns": table.column_names,
        "status": "Two-row schema/issue inspection only; no issue-resolution experiment performed",
        "reference_leakage": "Gold patch and test patch separated from problem inputs",
        "execution": "No eval_script, patch or dataset code executed",
        "license": "Benchmark harness MIT; upstream issue/code rights must be checked separately. Raw data not redistributed.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path)
    parser.add_argument("--jsonl", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.parquet) == bool(args.jsonl):
        parser.error("Select exactly one of --parquet or --jsonl")
    result = (
        prepare(args.parquet, args.out)
        if args.parquet
        else prepare_jsonl(args.jsonl, args.out)
    )
    args.summary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
