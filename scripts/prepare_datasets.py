"""Bounded, offline dataset preparation. Never extracts an archive to filesystem paths."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import textwrap
import zipfile


def apply_patch(old: str, patch: str) -> str:
    """Reconstruct post-change source from oldf + unified diff, never from msg/target."""
    source = old.splitlines(keepends=True)
    output = []
    cursor = 0
    in_hunk = False
    for line in patch.splitlines(keepends=True):
        header = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", line)
        if header:
            start = max(0, int(header[1]) - 1)
            if start < cursor:
                raise ValueError("Overlapping hunks")
            output.extend(source[cursor:start])
            cursor = start
            in_hunk = True
            continue
        if not in_hunk or line.startswith("\\"):
            continue
        if line.startswith((" ", "-")):
            if cursor >= len(source) or source[cursor].rstrip("\r\n") != line[
                1:
            ].rstrip("\r\n"):
                raise ValueError("Patch context mismatch")
            if line.startswith(" "):
                output.append(source[cursor])
            cursor += 1
        elif line.startswith("+"):
            output.append(line[1:])
    if not in_hunk:
        raise ValueError("No unified diff hunks")
    output.extend(source[cursor:])
    return "".join(output)


def codereviewer(archive: Path, output: Path, limit=5):
    output.mkdir(parents=True, exist_ok=True)
    inputs, references = [], []
    examined = rejected = 0
    with zipfile.ZipFile(archive) as zipped:
        member = "Comment_Generation/msg-test.jsonl"
        with zipped.open(member) as stream:
            for raw in stream:
                examined += 1
                if examined > 20000:
                    break
                if len(raw) > 1_000_000:
                    rejected += 1
                    continue
                row = json.loads(raw)
                if row.get("lang") not in ("py", "python"):
                    continue
                try:
                    code = apply_patch(row["oldf"], row["patch"])
                    if len(code.encode("utf-8")) > 50000:
                        raise ValueError("Source exceeds review limit")
                    ast.parse(code)
                except (ValueError, SyntaxError, KeyError):
                    rejected += 1
                    continue
                ident = str(row["id"])
                inputs.append(
                    {
                        "id": ident,
                        "filename": f"codereviewer_{ident}.py",
                        "code": code,
                        "provenance": {
                            "archive": "Comment_Generation.zip",
                            "member": member,
                            "project": row.get("proj"),
                            "sha256": hashlib.sha256(code.encode()).hexdigest(),
                        },
                    }
                )
                references.append({"id": ident, "comment": row["msg"]})
                if len(inputs) >= limit:
                    break
    for name, rows in [("inputs.jsonl", inputs), ("references.jsonl", references)]:
        (output / name).write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
    summary = {
        "dataset": "Microsoft CodeReviewer Comment Generation",
        "split": "test",
        "selected": len(inputs),
        "rows_examined": examined,
        "rejected_candidates": rejected,
        "selection": "First parseable Python post-change files under 50 KB; no manual cherry-picking",
        "archive_bytes": archive.stat().st_size,
        "references_separate": True,
        "license_status": "Dataset archive license not established from Zenodo metadata; local research only, no raw redistribution.",
    }
    (output / "preparation.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def bugsinpy(raw_file: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    rows = json.loads(raw_file.read_text(encoding="utf-8"))
    inputs, references = [], []
    for row in rows:
        source = row["source"]
        targets = []
        cursor = 0
        for line in row["patch"].splitlines():
            match = re.match(r"@@ -(\d+)", line)
            if match:
                cursor = int(match[1])
                continue
            if line.startswith(("---", "+++")):
                continue
            if line.startswith("-"):
                targets.append(cursor)
                cursor += 1
            elif line.startswith(" "):
                cursor += 1
        target = targets[0]
        nodes = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                if start <= target <= node.end_lineno:
                    nodes.append((node.end_lineno - start, node, start))
        if not nodes:
            raise ValueError(f"No enclosing definition for bug {row['id']}")
        _, node, start = min(nodes, key=lambda x: x[0])
        code = (
            textwrap.dedent("\n".join(source.splitlines()[start - 1 : node.end_lineno]))
            + "\n"
        )
        if len(code.encode()) > 50000:
            raise ValueError("Extracted definition exceeds limit")
        refs = dict(re.findall(r'(\w+)="([^"]*)"', row["info"]))
        ident = f"black-{row['id']}"
        inputs.append(
            {
                "id": ident,
                "filename": f"black_{row['id']}.py",
                "code": code,
                "provenance": {
                    "dataset": "BugsInPy",
                    "project": "psf/black",
                    **refs,
                    "source_path": "black.py",
                    "span": [start, node.end_lineno],
                    "transform": "enclosing definition, dedent only",
                    "sha256": hashlib.sha256(code.encode()).hexdigest(),
                },
            }
        )
        references.append(
            {
                "id": ident,
                "changed_lines": [
                    n - start + 1 for n in targets if start <= n <= node.end_lineno
                ],
                "patch": row["patch"],
            }
        )
    for name, values in [("inputs.jsonl", inputs), ("references.jsonl", references)]:
        (output / name).write_text(
            "\n".join(json.dumps(v) for v in values) + "\n", encoding="utf-8"
        )
    return {
        "dataset": "BugsInPy",
        "selected": len(inputs),
        "mode": "Static inspection of extracted real buggy definitions",
        "tests_reproduced": False,
        "warning": "Missing module context can cause unrelated undefined-name findings. "
        "Changed-line overlap is a localization proxy, not proof of detecting the known bug.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--codereviewer-zip", type=Path)
    parser.add_argument("--bugsinpy-raw", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error("limit must be 1–10")
    if args.codereviewer_zip:
        print(
            json.dumps(
                codereviewer(args.codereviewer_zip, args.out, args.limit), indent=2
            )
        )
    elif args.bugsinpy_raw:
        print(json.dumps(bugsinpy(args.bugsinpy_raw, args.out), indent=2))
    else:
        parser.error("Select a supplied archive or raw manifest")
