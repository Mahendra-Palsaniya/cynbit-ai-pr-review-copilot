import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest
from copilot.aggregation import aggregate
from copilot.ai import add_ai_review, build_input, validate_ai_output
from copilot.export import review_pdf
from copilot.inputs import decode_upload, safe_filename
from copilot.models import AIReview
from copilot.review import review_code
from scripts.prepare_datasets import apply_patch


def ai_payload(**changes):
    value = dict(
        id="AI-1",
        title="Possible zero division",
        category="bug",
        severity="medium",
        line_start=2,
        line_end=2,
        evidence="return 1 / x",
        explanation="Zero x raises ZeroDivisionError.",
        impact="The caller may fail for zero.",
        suggested_fix="Handle zero explicitly and test it.",
        confidence=0.8,
        source="AI",
    )
    value.update(changes)
    return json.dumps({"summary": "Check the zero case.", "findings": [value]})


@pytest.mark.parametrize(
    "name,data",
    [
        ("bad.txt", b"x=1"),
        ("empty.py", b""),
        ("big.py", b"x" * 50001),
        ("encoding.py", b"\xff\xfeinvalid"),
        ("null.py", b"x=\x00"),
    ],
    ids=["extension", "empty", "large", "encoding", "null"],
)
def test_upload_rejection(name, data):
    with pytest.raises(ValueError):
        decode_upload(name, data)


def test_upload_encoding_and_filename():
    name, code = decode_upload("../../safe.py", b"\xef\xbb\xbfx=1\n")
    assert name == "safe.py" and code == "x=1\n"
    assert safe_filename("..\\safe.py") == "safe.py"
    assert "caf" in decode_upload("latin.py", b'# coding: latin-1\nname="caf\xe9"')[1]


def test_structure_extraction():
    result = review_code(
        "import math\nclass A:\n    def f(self):\n        return math.pi\n"
    )
    assert result.structure["imports"][0]["line"] == 1
    assert result.structure["classes"][0]["name"] == "A"
    assert result.structure["functions"][0]["line_end"] == 4


def test_duplicates_keep_distinct_issues():
    result = review_code("try:\n    print(1)\nexcept:\n    pass\n")
    bare = [f for f in result.findings if "BARE_EXCEPT" in f.related_rules]
    assert len(bare) == 1 and set(bare[0].sources) == {"AST", "Ruff"}
    assert "E722" in bare[0].related_rules
    assert any(f.rule == "B110" for f in result.findings)
    assert len(aggregate(result.findings * 2)) == len(result.findings)


@pytest.mark.parametrize(
    "changes",
    [
        {"line_start": 0},
        {"line_end": 1},
        {"line_end": 99},
        {"confidence": 1.5},
        {"source": "Ruff"},
        {"evidence": "not in the file"},
        {"category": "imaginary"},
    ],
    ids=[
        "zero-line",
        "reversed",
        "outside",
        "confidence",
        "source",
        "evidence",
        "category",
    ],
)
def test_invalid_ai_findings(changes):
    with pytest.raises((ValidationError, ValueError)):
        validate_ai_output(ai_payload(**changes), "def f(x):\n    return 1 / x\n")


def test_valid_ai_schema_and_no_reference_input():
    parsed = validate_ai_output(ai_payload(), "def f(x):\n    return 1 / x\n")
    assert parsed.findings[0].source == "AI"
    schema = AIReview.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["AIFinding"]["additionalProperties"] is False
    text = build_input("x=1", review_code("x=1"))
    assert set(json.loads(text)) == {
        "filename",
        "numbered_source",
        "static_findings",
        "structure",
    }


@pytest.mark.parametrize(
    "error_name",
    ["RateLimitError", "APITimeoutError", "AuthenticationError", "RuntimeError"],
)
def test_provider_errors_keep_static(error_name, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    baseline = review_code("import os")
    failure = type(error_name, (Exception,), {})("sensitive error text")
    with patch("openai.OpenAI", side_effect=failure):
        add_ai_review(baseline, "import os", True)
    assert len(baseline.findings) == 1
    assert "sensitive" not in baseline.status["AI"]
    assert baseline.ai_latency_seconds is not None


def test_structured_provider_success(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    source = "def f(x):\n    return 1 / x\n"
    response = SimpleNamespace(
        output_text=ai_payload(),
        status="completed",
        usage=SimpleNamespace(input_tokens=120, output_tokens=80),
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: response))
    with patch("openai.OpenAI", return_value=client):
        result = add_ai_review(review_code(source), source, True)
    assert result.findings[0].source == "AI"
    assert result.usage["cost_usd"] is None


@pytest.mark.parametrize("output", ["not json", '{"summary":"x","findings":[{}]}'])
def test_malformed_provider_response(output, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    response = SimpleNamespace(output_text=output, status="completed")
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: response))
    with patch("openai.OpenAI", return_value=client):
        result = add_ai_review(review_code("import os"), "import os", True)
    assert result.findings[0].source == "Ruff"
    assert "validation" in result.status["AI"]


def test_pdf_export_untrusted_text():
    result = review_code('name = "<script> & text"\nprint(missing)')
    result.findings[0].title = "<b>not markup</b>"
    data = review_pdf(result)
    assert data.startswith(b"%PDF-") and b"%%EOF" in data
    assert len(data) > 1000


def test_patch_reconstruction_and_mismatch():
    assert apply_patch("x=1\n", "@@ -1 +1 @@\n-x=1\n+x=2\n") == "x=2\n"
    with pytest.raises(ValueError):
        apply_patch("different\n", "@@ -1 +1 @@\n-x=1\n+x=2\n")


def test_pdf_preserves_per_file_location(monkeypatch):
    import copilot.export as exporter

    result = review_code("missing_name\n", "first.py")
    result.filename = "owner/repository#1"
    result.findings[0].filename = "src/second.py"
    paragraphs = []
    original = exporter.Paragraph

    def capture(text, style):
        paragraphs.append(text)
        return original(text, style)

    monkeypatch.setattr(exporter, "Paragraph", capture)
    assert exporter.review_pdf(result).startswith(b"%PDF-")
    assert any("src/second.py | Ruff / F821 | lines 1-1" in p for p in paragraphs)


def test_ui_result_survives_filter_rerun():
    app = AppTest.from_file("app.py", default_timeout=15).run()
    next(b for b in app.button if b.label == "Review code").click().run(timeout=30)
    assert not app.exception
    result = app.session_state["active"]
    app.multiselect[0].set_value(["high"]).run()
    assert app.session_state["active"].id == result.id
    assert not app.exception


@pytest.mark.parametrize(
    "page",
    [
        "Dashboard",
        "Code Review",
        "Pull Requests",
        "Review History",
        "Security Analysis",
        "Code Quality",
        "Evaluation",
        "Settings",
        "About Project",
    ],
)
def test_all_navigation_pages(page):
    app = AppTest.from_file("app.py", default_timeout=15).run()
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception


def test_same_rule_same_line_different_columns_survive():
    result = review_code("print(missing, other)")
    assert len([f for f in result.findings if f.rule == "F821"]) == 2


def test_session_history_setting_persists():
    app = AppTest.from_file("app.py", default_timeout=15).run()
    app.sidebar.radio[0].set_value("Settings").run()
    next(
        c
        for c in app.checkbox
        if c.label == "Keep previous reviews in this browser session"
    ).check().run()
    app.sidebar.radio[0].set_value("Code Review").run()
    next(b for b in app.button if b.label == "Review code").click().run(timeout=30)
    assert len(app.session_state["history"]) == 1
    assert not app.exception


def test_swebench_reference_split(tmp_path):
    from scripts.inspect_swebench import prepare_jsonl

    row = {
        "instance_id": "case-1",
        "repo": "example/repo",
        "base_commit": "0" * 40,
        "problem_statement": "Reported behavior",
        "patch": "GOLD_SECRET",
        "test_patch": "TEST_SECRET",
    }
    path = tmp_path / "subset.jsonl"
    path.write_text(json.dumps(row) + "\n")
    prepare_jsonl(path, tmp_path / "prepared")
    source = (tmp_path / "prepared/inputs.jsonl").read_text()
    assert "GOLD_SECRET" not in source and "TEST_SECRET" not in source
    assert "Reported behavior" in source


def test_duplicate_ai_ids_rejected():
    value = json.loads(ai_payload())
    value["findings"] *= 2
    with pytest.raises(ValueError):
        validate_ai_output(json.dumps(value), "def f(x):\n    return 1 / x\n")
