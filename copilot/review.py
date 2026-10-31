"""Hybrid orchestration; submitted Python is never executed."""

import ast
import json
from pathlib import Path
import subprocess  # nosec B404
import sys
import tempfile
import time
from copilot.aggregation import aggregate
from copilot.context import contextual_findings
from copilot.inputs import MAX_BYTES, safe_filename, validate_source
from copilot.models import Finding, Review

__all__ = ["MAX_BYTES", "Finding", "Review", "review_code", "explain_with_llm"]
FIXES = {
    "F401": "Remove the unused import after checking for intentional import side effects.",
    "F821": "Define the name or correct its spelling; add a test exercising this path.",
    "E722": "Catch the specific expected exception instead of catching all exceptions.",
    "B307": "Avoid eval on untrusted input. Use a constrained parser for the intended input language.",
    "B101": "Use an explicit validation condition and raise an exception for runtime input checks.",
    "B110": "Handle expected failures without silently swallowing unrelated exceptions.",
    "B602": "Pass an argument list with shell=False and validate user-supplied arguments.",
}


def _run(module: str, args: list[str], cwd: str) -> list | dict:
    if module not in ("ruff", "bandit"):
        raise ValueError("Unsupported analyzer")
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    if result.returncode not in (0, 1) or len(result.stdout) > 2_000_000:
        raise RuntimeError("Analyzer failed or returned excessive output")
    return json.loads(result.stdout)


def review_code(code: str, filename: str = "submitted.py", progress=None) -> Review:
    start = time.perf_counter()
    code = validate_source(code)
    filename = safe_filename(filename)
    lines = code.splitlines()
    result = Review(
        filename=filename,
        status={
            "AST": "not run",
            "ruff": "not run",
            "bandit": "not run",
            "AI": "disabled",
        },
    )

    def emit(
        source,
        rule,
        line,
        title,
        explanation,
        severity="medium",
        category="quality",
        end=None,
        confidence=1.0,
        column=1,
        suggested_fix=None,
    ):
        line = min(max(1, line), len(lines))
        end = min(max(line, end or line), len(lines))
        return Finding(
            id=f"{source}-{rule}-{line}-{column}",
            title=title,
            category=category,
            severity=severity,
            line_start=line,
            line_end=end,
            evidence="\n".join(lines[line - 1 : end]),
            explanation=explanation,
            impact="Review the rule in context; detection does not establish runtime exploitability.",
            suggested_fix=suggested_fix
            or FIXES.get(rule, "Review the documented rule and add a regression test."),
            confidence=confidence,
            source=source,
            rule=rule,
            filename=filename,
            column=column,
            sources=[source],
            related_rules=[rule],
        )

    if progress:
        progress("Parsing Python structure", 10)
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        result.status["AST"] = "invalid input"
        result.findings = [
            emit(
                "AST",
                "SYNTAX",
                getattr(error, "lineno", 1) or 1,
                "Invalid Python syntax",
                "Python could not parse this source.",
                "high",
                "bug",
                suggested_fix="Correct the syntax before reviewing the remaining file.",
            )
        ]
        result.summary = "Source could not be parsed; other analyzers were not run."
        result.elapsed_seconds = time.perf_counter() - start
        return result
    result.status["AST"] = "completed"
    structure = {
        "imports": [],
        "functions": [],
        "classes": [],
        "line_count": len(lines),
    }
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            structure["imports"].append(
                {"name": ast.unparse(node), "line": node.lineno}
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            structure["functions"].append(
                {
                    "name": node.name,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                    "arguments": [a.arg for a in node.args.args],
                }
            )
            defaults = node.args.defaults + [
                d for d in node.args.kw_defaults if d is not None
            ]
            if any(isinstance(d, (ast.List, ast.Dict, ast.Set)) for d in defaults):
                result.findings.append(
                    emit(
                        "AST",
                        "MUTABLE_DEFAULT",
                        node.lineno,
                        "Mutable function default",
                        "A mutable default object persists across function calls.",
                        category="bug",
                        suggested_fix="Use None as default; create the collection inside the function.",
                    )
                )
        if isinstance(node, ast.ClassDef):
            structure["classes"].append(
                {
                    "name": node.name,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                }
            )
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            result.findings.append(
                emit(
                    "AST",
                    "BARE_EXCEPT",
                    node.lineno,
                    "Bare except handler",
                    "Bare except also catches SystemExit and KeyboardInterrupt.",
                    category="maintainability",
                    suggested_fix=FIXES["E722"],
                )
            )
    result.structure = structure
    result.findings.extend(contextual_findings(tree, code, filename))
    result.status["Local context"] = "completed; key-free AST heuristics, not an LLM"
    with tempfile.TemporaryDirectory(prefix="cynbit-review-") as directory:
        path = Path(directory) / "submitted.py"
        path.write_text(code, encoding="utf-8")
        for tool in ("ruff", "bandit"):
            if progress:
                progress(f"Running {tool.title()}", 35 if tool == "ruff" else 60)
            try:
                findings = []
                if tool == "ruff":
                    data = _run(
                        tool,
                        [
                            "check",
                            "--isolated",
                            "--no-cache",
                            "--ignore-noqa",
                            "--select",
                            "E4,E7,E9,F",
                            "--output-format",
                            "json",
                            str(path),
                        ],
                        directory,
                    )
                    for item in data:
                        findings.append(
                            emit(
                                "Ruff",
                                item["code"],
                                item["location"]["row"],
                                item["message"],
                                item["message"],
                                "high" if item["code"] == "F821" else "low",
                                "bug" if item["code"] == "F821" else "quality",
                                end=item.get("end_location", {}).get("row"),
                                column=item["location"]["column"],
                            )
                        )
                else:
                    data = _run(
                        tool,
                        ["-q", "-f", "json", "--ignore-nosec", str(path)],
                        directory,
                    )
                    if data.get("errors"):
                        raise RuntimeError("Bandit could not parse source")
                    for item in data["results"]:
                        findings.append(
                            emit(
                                "Bandit",
                                item["test_id"],
                                item["line_number"],
                                item["test_name"].replace("_", " ").title(),
                                item["issue_text"],
                                item["issue_severity"].lower(),
                                "security",
                                confidence={
                                    "HIGH": 0.95,
                                    "MEDIUM": 0.7,
                                    "LOW": 0.4,
                                }.get(item["issue_confidence"], 0.4),
                                column=max(1, item.get("col_offset", 0) + 1),
                            )
                        )
                result.findings.extend(findings)
                result.status[tool] = "completed"
            except (
                OSError,
                subprocess.TimeoutExpired,
                RuntimeError,
                ValueError,
                KeyError,
                TypeError,
            ):
                result.status[tool] = "unavailable or failed; results are incomplete"
    result.findings = aggregate(result.findings)
    complete = all(result.status[t] == "completed" for t in ("AST", "ruff", "bandit"))
    result.summary = (
        f"{len(result.findings)} static findings. "
        + (
            "All static analyzers completed."
            if complete
            else "Some checks are incomplete."
        )
        + " Human review required; absence of findings is not a safety guarantee."
    )
    result.elapsed_seconds = time.perf_counter() - start
    if progress:
        progress("Static review complete", 80)
    return result


def explain_with_llm(review: Review, code: str, consent: bool = False) -> str:
    from copilot.ai import add_ai_review

    add_ai_review(review, code, consent)
    return review.ai_summary or review.status["AI"]
