"""Validated review schema. AI evidence remains a hypothesis."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["low", "medium", "high", "critical"]
Category = Literal[
    "bug", "security", "quality", "maintainability", "performance", "testing"
]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    category: Category
    severity: Severity
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    evidence: str
    explanation: str
    impact: str
    suggested_fix: str
    confidence: float = Field(ge=0, le=1)
    source: Literal["AST", "Ruff", "Bandit", "AI"]
    rule: str
    filename: str = "submitted.py"
    column: int = Field(default=1, ge=1)
    sources: list[str] = Field(default_factory=list)
    related_rules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_lines(self):
        if self.line_end < self.line_start:
            raise ValueError("line_end must be at least line_start")
        return self

    @property
    def tool(self):
        return self.source

    @property
    def line(self):
        return self.line_start

    @property
    def message(self):
        return self.explanation

    @property
    def suggestion(self):
        return self.suggested_fix


class Review(BaseModel):
    id: str = Field(default_factory=lambda: "REV-" + uuid4().hex[:8].upper())
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    filename: str = "submitted.py"
    findings: list[Finding] = Field(default_factory=list)
    status: dict[str, str] = Field(default_factory=dict)
    structure: dict = Field(default_factory=dict)
    summary: str = ""
    ai_summary: str = ""
    elapsed_seconds: float = 0
    ai_latency_seconds: float | None = None
    usage: dict = Field(default_factory=dict)


class AIFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    category: Category
    severity: Severity
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    evidence: str
    explanation: str
    impact: str
    suggested_fix: str
    confidence: float = Field(ge=0, le=1)
    source: Literal["AI"]

    @model_validator(mode="after")
    def ordered_lines(self):
        if self.line_end < self.line_start:
            raise ValueError("Invalid line range")
        return self


class AIReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    findings: list[AIFinding]
