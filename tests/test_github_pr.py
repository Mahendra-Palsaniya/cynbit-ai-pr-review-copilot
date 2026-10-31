import base64
from io import BytesIO
from urllib.error import HTTPError, URLError
from unittest.mock import patch
import pytest
from streamlit.testing.v1 import AppTest
from copilot.github_pr import (
    GitHubClient,
    GitHubError,
    SlidingWindowLimiter,
    changed_lines,
    parse_pr_url,
)
from copilot.review import review_code

SOURCE = "def average(values):\n    return sum(values) / len(values)\n"
HEAD = "a" * 40
BLOB = "b" * 40
URL = "https://github.com/example/project/pull/12"


def metadata(head=HEAD):
    return {
        "title": "Handle averages",
        "user": {"login": "author"},
        "state": "open",
        "head": {"sha": head, "ref": "fix"},
        "base": {"ref": "main"},
        "changed_files": 1,
        "labels": [{"name": "bug"}],
        "requested_reviewers": [{"login": "reviewer"}],
        "assignees": [],
    }


def client_for(files=None, fail_blob=False, token=None):
    calls = []

    def transport(method, path, payload):
        calls.append((method, path, payload))
        if method == "POST":
            return {"html_url": URL + "#review-1"}
        if "/git/blobs/" in path:
            if fail_blob:
                raise GitHubError("File unavailable")
            return {
                "encoding": "base64",
                "size": len(SOURCE),
                "content": base64.b64encode(SOURCE.encode()).decode(),
            }
        if "/files?" in path:
            return (
                files
                if files is not None
                else [
                    {
                        "filename": "src/average.py",
                        "status": "added",
                        "sha": BLOB,
                        "patch": "@@ -0,0 +1,2 @@\n+def average(values):\n+    return sum(values) / len(values)",
                    }
                ]
            )
        return metadata()

    return GitHubClient(
        token=token, transport=transport, limiter=SlidingWindowLimiter(1000)
    ), calls


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b/pull/1",
        "https://github.com.evil/a/b/pull/1",
        "https://user:password@github.com/a/b/pull/1",
        "https://github.com:443/a/b/pull/1",
        "https://github.com/a/b/issues/1",
        "https://github.com/a/b/pull/0",
        "https://github.com/a/../pull/1",
        "https://github.com/a/b/pull/1?token=hidden",
        "https://127.0.0.1/a/b/pull/1",
        "x" * 301,
    ],
    ids=[
        "http",
        "host",
        "userinfo",
        "port",
        "issue",
        "zero",
        "traversal",
        "query",
        "ip",
        "length",
    ],
)
def test_invalid_urls(url):
    with pytest.raises(GitHubError):
        parse_pr_url(url)


def test_valid_url_and_diff_mapping():
    assert parse_pr_url(URL) == ("example", "project", 12)
    assert changed_lines("@@ -1,3 +1,4 @@\n a\n-b\n+B\n+C\n c") == {2, 3}


def test_public_pr_review_and_evidence():
    client, calls = client_for()
    bundle = client.read_pr(URL)
    assert bundle.metadata["author"] == "author"
    assert bundle.head_sha == HEAD
    assert bundle.review.findings[0].filename == "src/average.py"
    assert bundle.review.findings[0].rule == "EMPTY_INPUT_DIVISION"
    assert bundle.review.findings[0].line_start == 2
    assert all(call[0] == "GET" for call in calls)
    assert client.token is None


def test_missing_blob_and_removed_files_are_explicit():
    client, _ = client_for(fail_blob=True)
    bundle = client.read_pr(URL)
    assert (
        bundle.files[0].skip_reason == "File unavailable" and not bundle.review.findings
    )
    client, _ = client_for(
        files=[{"filename": "gone.py", "status": "removed", "sha": BLOB}]
    )
    assert "Deleted" in client.read_pr(URL).files[0].skip_reason


def test_malformed_file_list():
    client, _ = client_for(files=["bad"])
    with pytest.raises(GitHubError):
        client.read_pr(URL)


def test_diff_filter_does_not_report_unchanged_line():
    client, _ = client_for(
        files=[
            {
                "filename": "a.py",
                "status": "modified",
                "sha": BLOB,
                "patch": "@@ -1,2 +1,2 @@\n-def old(values):\n+def average(values):\n     return sum(values) / len(values)",
            }
        ]
    )
    assert not client.read_pr(URL).review.findings


def test_request_limits_and_python_file_limit():
    limiter = SlidingWindowLimiter(1, 60)
    limiter.acquire()
    with pytest.raises(GitHubError):
        limiter.acquire()
    files = [
        {"filename": f"f{i}.py", "status": "added", "sha": BLOB, "patch": "+x"}
        for i in range(11)
    ]
    client, _ = client_for(files=files)
    result = client.read_pr(URL)
    assert sum(bool(f.code) for f in result.files) == 10
    assert "limit" in result.files[-1].skip_reason


def test_unauthorized_publishing_never_writes():
    client, calls = client_for(token="test-only-token")
    bundle = client.read_pr(URL)
    with pytest.raises(GitHubError):
        client.publish(bundle, [bundle.review.findings[0].id])
    assert not any(method == "POST" for method, _, _ in calls)


def test_publishing_requires_token_and_mapped_line():
    client, _ = client_for()
    bundle = client.read_pr(URL)
    with pytest.raises(GitHubError):
        client.publish(bundle, [bundle.review.findings[0].id], True)
    client, calls = client_for(token="test-only-token")
    bundle = client.read_pr(URL)
    bundle.files[0].added_lines = []
    with pytest.raises(GitHubError):
        client.publish(bundle, [bundle.review.findings[0].id], True)
    assert not any(method == "POST" for method, _, _ in calls)


def test_authorized_publish_payload_is_comment_only():
    client, calls = client_for(token="test-only-token")
    bundle = client.read_pr(URL)
    client.publish(bundle, [bundle.review.findings[0].id], True)
    payload = calls[-1][2]
    assert payload["event"] == "COMMENT" and payload["commit_id"] == HEAD
    assert (
        payload["comments"][0]["line"] == 2
        and payload["comments"][0]["side"] == "RIGHT"
    )
    assert "test-only-token" not in str(payload)


def test_changed_head_blocks_publication():
    client, _ = client_for(token="test-only-token")
    bundle = client.read_pr(URL)
    client.transport = lambda *args: metadata("c" * 40)
    with pytest.raises(GitHubError, match="head changed"):
        client.publish(bundle, [bundle.review.findings[0].id], True)


@pytest.mark.parametrize(
    "failure",
    [URLError("sensitive"), HTTPError("url", 403, "token-sensitive", {}, None)],
)
def test_api_errors_are_sanitized(failure):
    client = GitHubClient(token="test-only-token", limiter=SlidingWindowLimiter(100))
    with patch.object(client.opener, "open", side_effect=failure):
        with pytest.raises(GitHubError) as error:
            client.request("GET", "/repos/a/b/pulls/1")
    assert "sensitive" not in str(error.value) and "test-only-token" not in str(
        error.value
    )


def test_malformed_json_response():
    client = GitHubClient(limiter=SlidingWindowLimiter(100))
    with patch.object(client.opener, "open", return_value=BytesIO(b"not json")):
        with pytest.raises(GitHubError):
            client.request("GET", "/repos/a/b/pulls/1")


def test_no_key_context_checks_and_guarded_negative():
    assert "EMPTY_INPUT_DIVISION" in {f.rule for f in review_code(SOURCE).findings}
    assert "ZERO_DENOMINATOR" in {f.rule for f in review_code("value=1/0").findings}
    assert "NONE_DEFAULT_ATTRIBUTE" in {
        f.rule
        for f in review_code("def f(value=None):\n    return value.strip()").findings
    }
    guarded = "def average(values):\n    if not values:\n        return None\n    return sum(values)/len(values)"
    assert not any(
        f.rule == "EMPTY_INPUT_DIVISION" for f in review_code(guarded).findings
    )


def test_pr_ui_invalid_url_is_visible_error():
    app = AppTest.from_file("app.py", default_timeout=15).run()
    app.sidebar.radio[0].set_value("Pull Requests").run()
    app.text_input[0].set_value("https://evil.example/pull/1")
    next(b for b in app.button if b.label == "Fetch and review PR").click().run()
    assert app.error and not app.exception


def test_malformed_metadata_types_are_rejected():
    client, _ = client_for()
    bad = metadata()
    bad["changed_files"] = "not an integer"
    client.transport = lambda *args: bad
    with pytest.raises(GitHubError):
        client.read_pr(URL)
