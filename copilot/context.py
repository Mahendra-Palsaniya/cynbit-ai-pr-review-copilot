"""Key-free contextual heuristics. These are AST rules, not an LLM."""

import ast
from copilot.models import Finding


def contextual_findings(tree: ast.AST, code: str, filename: str) -> list[Finding]:
    lines = code.splitlines()
    findings = []

    def emit(node, rule, title, explanation, impact, fix):
        findings.append(
            Finding(
                id=f"AST-{rule}-{node.lineno}",
                title=title,
                category="bug",
                severity="medium",
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                evidence="\n".join(lines[node.lineno - 1 : node.end_lineno]),
                explanation=explanation,
                impact=impact,
                suggested_fix=fix,
                confidence=0.8,
                source="AST",
                rule=rule,
                filename=filename,
                sources=["AST"],
                related_rules=[rule],
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Div, ast.FloorDiv, ast.Mod)
        ):
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                emit(
                    node,
                    "ZERO_DENOMINATOR",
                    "Literal zero denominator",
                    "This expression divides or takes a remainder by literal zero.",
                    "If reached with numeric operands, the operation raises ZeroDivisionError.",
                    "Correct the denominator and add a regression test for this path.",
                )
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
        ):
            body = body[1:]
        # Deliberately narrow: a single direct return, with no internal guard or side effects.
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            continue
        expression = body[0].value
        for part in ast.walk(expression) if expression else []:
            if isinstance(part, ast.BinOp) and isinstance(
                part.op, (ast.Div, ast.FloorDiv)
            ):
                denominator = part.right
                if (
                    isinstance(denominator, ast.Call)
                    and isinstance(denominator.func, ast.Name)
                    and denominator.func.id == "len"
                    and len(denominator.args) == 1
                ):
                    emit(
                        part,
                        "EMPTY_INPUT_DIVISION",
                        "Potential division by an empty collection length",
                        "This direct-return function divides by len(...) without an internal empty-input guard. "
                        "An external non-empty precondition may make this intentional.",
                        "An empty collection can raise ZeroDivisionError unless callers guarantee otherwise.",
                        "Define the empty-input contract, add a guard if needed, and test empty and non-empty inputs.",
                    )
            if isinstance(part, ast.Attribute) and isinstance(part.value, ast.Name):
                arguments = node.args.posonlyargs + node.args.args
                default_names = {
                    a.arg
                    for a, d in zip(
                        arguments[-len(node.args.defaults) :], node.args.defaults
                    )
                    if isinstance(d, ast.Constant) and d.value is None
                }
                default_names.update(
                    a.arg
                    for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults)
                    if isinstance(d, ast.Constant) and d.value is None
                )
                if part.value.id in default_names:
                    emit(
                        part,
                        "NONE_DEFAULT_ATTRIBUTE",
                        "Attribute access on a None default",
                        f"This direct-return function accesses an attribute on {part.value.id}, whose default is None.",
                        "Calling the function without that argument can raise AttributeError.",
                        "Handle None explicitly or require the argument; test a call using the default value.",
                    )
    return findings
