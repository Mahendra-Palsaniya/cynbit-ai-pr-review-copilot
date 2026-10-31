import subprocess
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from copilot.review import Review, explain_with_llm, review_code


@pytest.mark.parametrize('source', ['', '  ', 'x' * 50001, 'é' * 25001], ids=['empty','space','oversize','unicode'])
def test_reject_input(source):
    with pytest.raises(ValueError):
        review_code(source)


def test_syntax_error():
    assert review_code('def broken(').findings[0].rule == 'SYNTAX'


def test_real_analyzers():
    result = review_code('import os\ndef f(items=[]):\n    return eval("1")\n')
    assert all(value == 'completed' for value in result.status.values())
    assert {'F401', 'B307', 'MUTABLE_DEFAULT'} <= {f.rule for f in result.findings}


def test_clean():
    assert not review_code('def add(a, b):\n    return a + b\n').findings


def test_never_execute(tmp_path):
    target = tmp_path / 'must_not_exist'
    review_code(f'open({str(target)!r}, "w").write("executed")')
    assert not target.exists()


def test_nosec_cannot_suppress_bandit():
    assert 'B307' in {f.rule for f in review_code('eval("1")  # nosec').findings}


@pytest.mark.parametrize('failure', [OSError(), subprocess.TimeoutExpired('tool', 15),
                                   ValueError(), RuntimeError()])
def test_tool_failure_retains_ast(failure):
    with patch('copilot.review._run', side_effect=failure):
        result = review_code('def f(a=[]):\n    return a')
    assert result.findings[0].rule == 'MUTABLE_DEFAULT'
    assert 'incomplete' in result.status['ruff']


def test_no_consent_does_not_call_provider():
    with patch.dict('os.environ', {'OPENAI_API_KEY': 'fake'}):
        assert 'Disabled' in explain_with_llm(Review(), 'x=1')


def test_missing_key(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert 'No API key' in explain_with_llm(Review(), 'x=1', True)


def test_provider_failure_redacts(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'fake')
    with patch('openai.OpenAI', side_effect=RuntimeError('secret-sensitive-error')):
        response = explain_with_llm(Review(), 'x=1', True)
    assert 'unavailable' in response and 'secret' not in response


def test_ui():
    app = AppTest.from_file('app.py').run()
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert 'findings' in app.subheader[0].value
