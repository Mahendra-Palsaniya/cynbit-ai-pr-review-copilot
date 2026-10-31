"""Bounded GitHub REST PR reading and explicitly authorized review publishing."""

import base64
from collections import deque
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, Field
from copilot.ai import add_ai_review
from copilot.models import Review
from copilot.review import review_code

MAX_PYTHON_FILES = 10
MAX_TOTAL_BYTES = 150_000


class GitHubError(ValueError):
    """Sanitized error suitable for UI display."""


class SlidingWindowLimiter:
    def __init__(self, limit=30, seconds=60):
        self.limit, self.seconds = limit, seconds
        self.events = deque()
        self.lock = threading.Lock()

    def acquire(self):
        now = time.monotonic()
        with self.lock:
            while self.events and self.events[0] <= now - self.seconds:
                self.events.popleft()
            if len(self.events) >= self.limit:
                raise GitHubError(
                    "Local GitHub request limit reached. Wait a minute and retry."
                )
            self.events.append(now)


LIMITER = SlidingWindowLimiter()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GitHubError(
            "GitHub redirected this request. Use the current canonical repository URL."
        )


def parse_pr_url(url: str) -> tuple[str, str, int]:
    if len(url) > 300:
        raise GitHubError("PR URL is too long.")
    try:
        value = urlsplit(url.strip())
        if (
            value.scheme != "https"
            or value.hostname != "github.com"
            or value.port is not None
            or value.username
            or value.password
            or value.query
            or value.fragment
        ):
            raise ValueError()
        match = re.fullmatch(
            r"/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})/pull/([1-9][0-9]{0,9})/?",
            value.path,
        )
        if not match or match[2] in (".", ".."):
            raise ValueError()
        return match[1], match[2], int(match[3])
    except (ValueError, TypeError) as error:
        raise GitHubError(
            "Use an HTTPS github.com/owner/repository/pull/number URL without query parameters."
        ) from error


def changed_lines(patch: str) -> set[int]:
    added = set()
    cursor = None
    for line in patch.splitlines():
        match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if match:
            cursor = int(match[1])
        elif cursor is not None:
            if line.startswith("+"):
                added.add(cursor)
                cursor += 1
            elif line.startswith(" "):
                cursor += 1
            elif not line.startswith(("-", "\\")):
                cursor = None
    return added


class PRFile(BaseModel):
    path: str
    status: str
    patch: str = ""
    added_lines: list[int] = Field(default_factory=list)
    code: str = ""
    skip_reason: str = ""


class PRBundle(BaseModel):
    owner: str
    repository: str
    number: int
    url: str
    head_sha: str
    metadata: dict
    files: list[PRFile]
    review: Review


class GitHubClient:
    def __init__(self, token=None, transport=None, limiter=None):
        self.token = token
        self.transport = transport
        self.limiter = limiter or LIMITER
        self.opener = build_opener(NoRedirect())

    def request(self, method: str, path: str, payload=None):
        self.limiter.acquire()
        if not path.startswith("/repos/") or "\n" in path:
            raise GitHubError("Unsupported GitHub endpoint.")
        if self.transport:
            return self.transport(method, path, payload)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Cynbit-Assessment-Review-Copilot",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            "https://api.github.com" + path, data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=12) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise GitHubError("GitHub response exceeds the supported size.")
            return json.loads(raw)
        except HTTPError as error:
            reason = {
                401: "GitHub credentials were rejected.",
                403: "GitHub access denied or API rate limit reached.",
                404: "PR or file not found, or private repository access is missing.",
                422: "GitHub rejected this review or its changed-line mapping.",
                429: "GitHub API rate limit reached. Try again later.",
            }.get(error.code, "GitHub API request failed.")
            raise GitHubError(reason) from None
        except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError):
            raise GitHubError(
                "GitHub is unavailable, timed out, or returned an invalid response."
            ) from None

    def read_pr(
        self, url: str, with_ai=False, api_key=None, model=None, progress=None
    ) -> PRBundle:
        owner, repository, number = parse_pr_url(url)
        prefix = f"/repos/{owner}/{repository}"
        metadata = self.request("GET", f"{prefix}/pulls/{number}")
        try:
            head = metadata["head"]["sha"]
            if not re.fullmatch(r"[a-f0-9]{40}", head):
                raise ValueError()
            safe_metadata = {
                "title": metadata["title"],
                "author": metadata["user"]["login"],
                "state": metadata["state"],
                "base_branch": metadata["base"]["ref"],
                "head_branch": metadata["head"]["ref"],
                "head_commit": head,
                "changed_files": metadata["changed_files"],
                "labels": [label["name"] for label in metadata.get("labels", [])],
                "reviewers": [
                    user["login"] for user in metadata.get("requested_reviewers", [])
                ],
                "assignees": [user["login"] for user in metadata.get("assignees", [])],
            }
            if (
                not isinstance(safe_metadata["changed_files"], int)
                or safe_metadata["changed_files"] < 0
                or not all(
                    isinstance(safe_metadata[k], str)
                    for k in ("title", "author", "state", "base_branch", "head_branch")
                )
                or not all(
                    isinstance(value, str)
                    for key in ("labels", "reviewers", "assignees")
                    for value in safe_metadata[key]
                )
            ):
                raise ValueError("Invalid metadata types")
            changed = self.request(
                "GET", f"{prefix}/pulls/{number}/files?per_page=100&page=1"
            )
            if not isinstance(changed, list):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise GitHubError(
                "GitHub returned malformed PR metadata or changed files."
            ) from None
        files = []
        combined = Review(
            filename=f"{owner}/{repository}#{number}",
            status={"GitHub": "metadata and file list fetched"},
        )
        count = total = attempts = 0
        for item in changed:
            if not isinstance(item, dict):
                raise GitHubError("GitHub returned malformed changed-file data.")
            try:
                path = item["filename"]
                if (
                    not isinstance(path, str)
                    or path.startswith("/")
                    or ".." in path.split("/")
                ):
                    raise ValueError()
                entry = PRFile(
                    path=path, status=item["status"], patch=item.get("patch", "")
                )
                files.append(entry)
                if not path.lower().endswith(".py"):
                    entry.skip_reason = "Not a Python file"
                    continue
                if item["status"] == "removed":
                    entry.skip_reason = "Deleted file has no head source"
                    continue
                if attempts >= MAX_PYTHON_FILES:
                    entry.skip_reason = "Ten-Python-file review limit reached"
                    continue
                attempts += 1
                sha = item["sha"]
                if not re.fullmatch(r"[a-f0-9]{40}", sha):
                    raise ValueError()
                blob = self.request("GET", f"{prefix}/git/blobs/{sha}")
                if blob["encoding"] != "base64" or blob["size"] > 50_000:
                    entry.skip_reason = "Unsupported encoding or file exceeds 50 KB"
                    continue
                raw = base64.b64decode("".join(blob["content"].split()), validate=True)
                total += len(raw)
                if len(raw) > 50_000 or total > MAX_TOTAL_BYTES:
                    entry.skip_reason = "Per-file or total PR source limit reached"
                    continue
                from copilot.inputs import decode_upload

                _, code = decode_upload(path, raw)
                entry.code = code
                entry.added_lines = sorted(changed_lines(entry.patch))
                count += 1
                if progress:
                    progress(f"Reviewing {path}", min(90, 10 + count * 7))
                review = review_code(code, path.rsplit("/", 1)[-1])
                if with_ai and review.status.get("AST") == "completed":
                    add_ai_review(review, code, True, api_key=api_key, model=model)
                for finding in review.findings:
                    finding.filename = path
                    finding.id = path + ":" + finding.id
                    if not entry.patch or any(
                        finding.line_start <= line <= finding.line_end
                        for line in entry.added_lines
                    ):
                        combined.findings.append(finding)
                for tool, status in review.status.items():
                    combined.status[f"{path} / {tool}"] = status
                combined.elapsed_seconds += review.elapsed_seconds
                if not entry.patch:
                    entry.skip_reason = "Diff unavailable: complete-file findings shown; inline publishing disabled"
            except GitHubError as error:
                entry.skip_reason = str(error)
                continue
            except (KeyError, TypeError, ValueError, UnicodeError):
                if files and files[-1].path == item.get("filename"):
                    files[
                        -1
                    ].skip_reason = "Malformed file data, invalid encoding, or unsupported Python content"
                else:
                    raise GitHubError(
                        "GitHub returned malformed changed-file data."
                    ) from None
        latest = self.request("GET", f"{prefix}/pulls/{number}")
        if not isinstance(latest, dict) or latest.get("head", {}).get("sha") != head:
            raise GitHubError(
                "PR head changed while fetching files. Review it again before proceeding."
            )
        safe_metadata["file_list_truncated"] = safe_metadata["changed_files"] > len(
            changed
        )
        combined.structure = {
            "github_pr": safe_metadata,
            "files": [f.path for f in files if f.code],
        }
        combined.summary = (
            f"{count} Python files analyzed; {len(combined.findings)} findings. "
        )
        combined.summary += "Only added-line findings are shown when a diff is available. Human review required."
        return PRBundle(
            owner=owner,
            repository=repository,
            number=number,
            url=f"https://github.com/{owner}/{repository}/pull/{number}",
            head_sha=head,
            metadata=safe_metadata,
            files=files,
            review=combined,
        )

    def publish(self, bundle: PRBundle, finding_ids: list[str], authorized=False):
        if authorized is not True:
            raise GitHubError("Explicit publishing authorization is required.")
        if not self.token:
            raise GitHubError(
                "Publishing requires a GitHub token with pull-request write permission."
            )
        prefix = f"/repos/{bundle.owner}/{bundle.repository}/pulls/{bundle.number}"
        current = self.request("GET", prefix)
        if (
            not isinstance(current, dict)
            or current.get("head", {}).get("sha") != bundle.head_sha
        ):
            raise GitHubError("PR head changed. Run a fresh review before publishing.")
        comments = []
        files = {file.path: file for file in bundle.files}
        for finding in bundle.review.findings:
            if finding.id not in finding_ids:
                continue
            file = files.get(finding.filename)
            matches = [
                line
                for line in (file.added_lines if file else [])
                if finding.line_start <= line <= finding.line_end
            ]
            if not matches:
                raise GitHubError(
                    "A selected finding is not mapped to an added diff line."
                )
            body = (
                f"Automated review assistance ({finding.source}; {finding.severity}). Human verification required.\n\n"
                f"{finding.title}\n\n{finding.explanation}\n\nSuggested improvement: {finding.suggested_fix}"
            )[:3000]
            comments.append(
                {
                    "path": finding.filename,
                    "line": matches[0],
                    "side": "RIGHT",
                    "body": body,
                }
            )
        if not 1 <= len(comments) <= 10:
            raise GitHubError("Select between one and ten mapped findings to publish.")
        return self.request(
            "POST",
            prefix + "/reviews",
            {
                "commit_id": bundle.head_sha,
                "event": "COMMENT",
                "body": "User-authorized automated review assistance.",
                "comments": comments,
            },
        )
