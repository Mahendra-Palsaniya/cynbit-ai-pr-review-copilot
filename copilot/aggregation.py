"""Conservative duplicate removal; a shared line is never enough."""

from copilot.models import Finding

RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def aggregate(findings: list[Finding]) -> list[Finding]:
    groups: dict[tuple, Finding] = {}
    for original in findings:
        finding = original.model_copy(deep=True)
        family = (
            "bare-except" if finding.rule in ("BARE_EXCEPT", "E722") else finding.rule
        )
        identity = (
            finding.filename,
            finding.line_start,
            finding.line_end,
            "AI" if finding.source == "AI" else "static",
            family,
            0 if family == "bare-except" else finding.column,
            finding.title.casefold() if finding.source == "AI" else "",
        )
        finding.sources = finding.sources or [finding.source]
        finding.related_rules = finding.related_rules or [finding.rule]
        if identity not in groups:
            groups[identity] = finding
            continue
        existing = groups[identity]
        existing.sources = sorted(set(existing.sources + finding.sources))
        existing.related_rules = sorted(
            set(existing.related_rules + finding.related_rules)
        )
        if RANK[finding.severity] > RANK[existing.severity]:
            existing.severity = finding.severity
    return sorted(
        groups.values(),
        key=lambda f: (-RANK[f.severity], f.line_start, f.source, f.rule),
    )
