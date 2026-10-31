"""Dark review workspace with honest session metadata and persistent result widgets."""

from collections import Counter
import difflib
import hmac
from html import escape
import json
import os
import time
from pathlib import Path

import streamlit as st
from copilot.ai import add_ai_review
from copilot.config import github_publish_code, github_token
from copilot.github_pr import GitHubClient, GitHubError
from copilot.export import review_pdf
from copilot.inputs import MAX_BYTES, decode_upload
from copilot.review import review_code

ROOT = Path(__file__).parent
NAV = [
    "Dashboard",
    "Code Review",
    "Pull Requests",
    "Review History",
    "Security Analysis",
    "Code Quality",
    "Evaluation",
    "Settings",
    "About Project",
]
SAMPLE = """import os
import time

def collect(value, items=[]):
    items.append(value)
    return items

def calculate(expression):
    return eval(expression)
"""
st.set_page_config(page_title="AI PR Review Copilot", page_icon="◈", layout="wide")
st.markdown(
    """<style>
.stApp {background:#121116;color:#e7e4ef}
.block-container {padding:2rem 1.6rem 3rem;max-width:1800px}
[data-testid="stSidebar"] {background:#19171f;border-right:1px solid #302b3b}
[data-testid="stSidebar"] .block-container {padding-top:1.5rem}
h1 {font-size:1.8rem!important;letter-spacing:-.04em} h2 {font-size:1.2rem!important}
h3 {font-size:1rem!important} p {font-size:.91rem}
[data-testid="stMetric"] {background:#201d29;border:1px solid #35303f;padding:14px;border-radius:12px}
[data-testid="stMetricValue"] {font-size:1.65rem}
[data-testid="stVerticalBlockBorderWrapper"]>div {border-color:#332d40!important;border-radius:12px}
.stTabs [data-baseweb="tab-list"] {gap:12px;border-bottom:1px solid #332d40}
.stTabs [aria-selected="true"] {color:#b9a4ff!important}
[data-testid="stButton"] button {border-radius:8px;text-align:left}
.eyebrow {color:#aa91f4;font:600 11px monospace;letter-spacing:.13em;text-transform:uppercase}
.panel-title {font-size:14px;font-weight:600;margin:0 0 12px;color:#e6e1ee}
.muted {color:#9992a6;font-size:12px}
.summary {background:#241f32;border:1px solid #46345f;border-radius:12px;padding:18px;margin-bottom:16px}
.finding {border:1px solid #38313f;border-left:3px solid #9b87f5;border-radius:10px;padding:14px;margin:12px 0}
.pill {display:inline-block;border-radius:5px;padding:3px 7px;font:600 10px monospace;letter-spacing:.04em}
.low {color:#91ddb7;background:#20372b}.medium {color:#efc16d;background:#3d3221}
.high,.critical {color:#f59eac;background:#40252d}.ai {color:#c6aeff;background:#33284b}
@media(max-width:1050px){.block-container{padding:1rem}h1{font-size:1.5rem!important}}
</style>""",
    unsafe_allow_html=True,
)

for key, value in {
    "history": [],
    "active": None,
    "active_code": "",
    "active_pr": None,
    "active_base": "",
    "upload_epoch": 0,
    "keep_history": False,
    "use_ai": False,
    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
}.items():
    if key not in st.session_state:
        st.session_state[key] = value


def configured_key():
    if os.getenv("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    try:
        return st.secrets.get("OPENAI_API_KEY")
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return None


def finding_card(f):
    label = "AI potential finding" if f.source == "AI" else "Static rule match"
    st.markdown(
        f'<div class="finding"><span class="pill {f.severity}">{escape(f.severity.upper())}</span> '
        f'<span class="pill ai">{escape(label)}</span><h3>{escape(f.title)}</h3>'
        f'<span class="muted">{escape(f.filename)} · L{f.line_start}-{f.line_end} · '
        f"{escape(' + '.join(f.sources))} · {escape(f.rule)}</span></div>",
        unsafe_allow_html=True,
    )
    st.code(f.evidence, language="python", line_numbers=True)
    st.text(f.explanation)
    with st.expander("Impact, suggested fix and confidence"):
        st.text(f.impact)
        st.text(f.suggested_fix)
        st.caption(
            f"Confidence: {f.confidence:.2f} — tool heuristic or model estimate, not a calibrated probability."
        )


with st.sidebar:
    st.markdown(
        '<div class="eyebrow">Developer workspace</div>', unsafe_allow_html=True
    )
    st.markdown("### ◈ AI PR REVIEW\nCOPILOT")
    st.caption("Python review assistance")
    icons = dict(
        zip(
            NAV,
            [
                ":material/dashboard:",
                ":material/code:",
                ":material/merge:",
                ":material/history:",
                ":material/security:",
                ":material/check_circle:",
                ":material/analytics:",
                ":material/settings:",
                ":material/info:",
            ],
        )
    )
    page = st.radio(
        "Workspace navigation",
        NAV,
        label_visibility="collapsed",
        format_func=lambda name: icons[name] + "  " + name,
    )
    st.divider()
    st.markdown("**Engine status**")
    st.caption("AST · Ruff · Bandit")
    st.caption(
        "AI credential configured"
        if configured_key()
        else "AI: no credential configured"
    )
    st.caption("Session-only storage · No code database")
    if st.button("Clear session reviews", use_container_width=True):
        st.session_state.history = []
        st.session_state.active = None
        st.session_state.active_pr = None
        st.session_state.active_code = ""
        st.session_state.active_base = ""
        st.session_state.editor = ""
        st.session_state.baseline = ""
        st.session_state.upload_epoch += 1
        st.rerun()

st.markdown(
    '<div class="eyebrow">Review workspace / Python</div>', unsafe_allow_html=True
)
heading, badge = st.columns([4, 1])
with heading:
    st.title("AI PR Review Copilot")
    st.caption("Key-free local review. Optional LLM suggestions with human judgment.")
with badge:
    st.markdown(
        '<span class="pill low">PYTHON WORKSPACE</span>', unsafe_allow_html=True
    )

if page == "Settings":
    st.subheader("Review and privacy settings")
    st.session_state.keep_history = st.checkbox(
        "Keep previous reviews in this browser session",
        value=st.session_state.keep_history,
        key="history_toggle",
    )
    st.info(
        "History includes source, evidence and findings only when enabled. It is kept in server session memory, "
        "not a database. Clear it using the sidebar. The current editor and current result remain in session memory."
    )
    st.session_state.model = st.text_input(
        "OpenAI model", value=st.session_state.model, key="model_input", max_chars=100
    )
    st.caption(
        "Default gpt-4.1-mini is configurable; account availability and pricing must be checked separately."
    )
    st.code(
        'OPENAI_API_KEY = "your-key"\nOPENAI_MODEL = "gpt-4.1-mini"', language="toml"
    )
    st.caption(
        "Example configuration only. Configure real values in Streamlit Secrets or your local environment. "
        "Never commit them. This app does not display configured values."
    )
    st.warning(
        "Enabling AI on a review sends that source and static findings to OpenAI. No automatic fixes or PR writes."
    )
    st.stop()

if page == "About Project":
    st.subheader("Cynbit internship assessment")
    st.write(
        "Independent proof of concept for a proposed developer-assistance opportunity. "
        "It is not an official Cynbit product or a replacement for human reviewers."
    )
    st.link_button(
        "Public repository",
        "https://github.com/Mahendra-Palsaniya/cynbit-ai-pr-review-copilot",
    )
    for name in ("AI_Opportunity_Report.md", "Technical_Approach_Report.md"):
        p = ROOT / "docs" / name
        if p.exists():
            st.download_button(
                name.replace("_", " ").replace(".md", ""),
                p.read_text(encoding="utf-8"),
                name,
            )
    st.info(
        "Public GitHub PRs can be fetched read-only without a token. Comment publishing requires a token and explicit authorization. No automatic merge actions are implemented. "
        "Uploaded code is never executed. Tool warnings are not proof of an exploitable vulnerability."
    )
    st.stop()

if page == "Evaluation":
    st.subheader("Evaluation evidence")
    st.caption(
        "Recorded offline runs. Synthetic fixture scores do not establish production accuracy."
    )
    for name in ("results.json", "dataset_results.json"):
        p = ROOT / "evaluation" / name
        if p.exists():
            values = json.loads(p.read_text(encoding="utf-8"))
            with st.expander(name, expanded=True):
                st.json({k: v for k, v in values.items() if k not in ("cases", "rows")})
                st.download_button(
                    "Download " + name, p.read_bytes(), name, "application/json"
                )
    st.stop()

if page == "Pull Requests":
    st.subheader("Review a real GitHub pull request")
    st.caption(
        "Public PRs need no token. Up to ten Python files and 150 KB total source. "
        "Read-only by default; findings are mapped to added lines when the diff is available."
    )
    pr_url = st.text_input(
        "GitHub PR URL",
        placeholder="https://github.com/owner/repository/pull/123",
        max_chars=300,
    )
    pr_ai = st.checkbox(
        "Send fetched Python source to OpenAI for optional LLM review",
        key="pr_ai_consent",
    )
    if st.button("Fetch and review PR", type="primary"):
        try:
            if time.monotonic() - st.session_state.get("last_pr_request", -1000) < 15:
                raise GitHubError("Wait 15 seconds between PR fetches.")
            st.session_state.last_pr_request = time.monotonic()
            progress = st.progress(0, text="Fetching GitHub metadata")
            client = GitHubClient(token=github_token())
            bundle = client.read_pr(
                pr_url,
                with_ai=pr_ai,
                api_key=configured_key(),
                model=st.session_state.model,
                progress=lambda message, value: progress.progress(value, text=message),
            )
            st.session_state.active = bundle.review
            st.session_state.active_pr = bundle
            st.session_state.active_code = next(
                (file.code for file in bundle.files if file.code), ""
            )
            st.session_state.active_base = ""
            if st.session_state.keep_history:
                entry = {
                    "review": bundle.review,
                    "code": st.session_state.active_code,
                    "base": "",
                    "pr": bundle,
                }
                st.session_state.history = ([entry] + st.session_state.history)[:10]
            progress.progress(100, text="GitHub review complete")
        except ValueError as error:
            st.error(str(error))

if page == "Review History" and not st.session_state.history:
    st.info(
        "No saved session reviews. Enable session history in Settings before reviewing to retain previous sessions."
    )

if page in ("Dashboard", "Code Review"):
    with st.expander(
        "New review · Paste or upload Python",
        expanded=page == "Code Review",
    ):
        left_input, right_input = st.columns([3, 2])
        with left_input:
            filename = st.text_input("File name", value="submitted.py", max_chars=100)
            code = st.text_area(
                "Python source",
                value=SAMPLE,
                height=270,
                max_chars=MAX_BYTES,
                key="editor",
            )
        with right_input:
            upload = st.file_uploader(
                "Upload a .py file (maximum 50 KB)",
                type=["py"],
                key="upload-" + str(st.session_state.upload_epoch),
            )
            st.caption(
                "Uploaded files override pasted source. Encoding declarations are honored; invalid encodings are rejected."
            )
            base = st.text_area(
                "Optional previous version for local diff",
                height=130,
                max_chars=MAX_BYTES,
                key="baseline",
            )
            consent = st.checkbox(
                "Send this source to OpenAI for contextual AI review",
                value=st.session_state.use_ai,
                key="ai_consent",
            )
            st.session_state.use_ai = consent
            st.caption(
                "No key is needed for static checks. AI output remains unverified."
            )
        st.caption(
            "Current code and findings stay in session memory. History is opt-in in Settings. "
            "Code is never executed; avoid confidential content. Exports include evidence."
        )
        if st.button("Review code", type="primary"):
            try:
                if (
                    time.monotonic() - st.session_state.get("last_local_review", -1000)
                    < 2
                ):
                    raise ValueError("Wait two seconds between source reviews.")
                st.session_state.last_local_review = time.monotonic()
                if upload is not None:
                    filename, code = decode_upload(upload.name, upload.getvalue())
                progress = st.progress(0, text="Validating source")

                def advance(message, value):
                    progress.progress(value, text=message)

                review = review_code(code, filename, progress=advance)
                if consent and review.status["AST"] == "completed":
                    advance("Requesting structured AI review", 85)
                    add_ai_review(
                        review,
                        code,
                        True,
                        api_key=configured_key(),
                        model=st.session_state.model,
                    )
                advance("Review complete", 100)
                entry = {"review": review, "code": code, "base": base, "pr": None}
                st.session_state.active = review
                st.session_state.active_pr = None
                st.session_state.active_code = code
                st.session_state.active_base = base
                if st.session_state.keep_history:
                    st.session_state.history = ([entry] + st.session_state.history)[:10]
            except ValueError as error:
                st.error(str(error))

active = st.session_state.active
if page == "Dashboard":
    cols = st.columns(4)
    metrics = [
        ("Current findings", len(active.findings) if active else 0),
        (
            "Security signals",
            sum(f.category == "security" for f in active.findings) if active else 0,
        ),
        (
            "AI hypotheses",
            sum(f.source == "AI" for f in active.findings) if active else 0,
        ),
        ("Saved sessions", len(st.session_state.history)),
    ]
    for col, (label, value) in zip(cols, metrics):
        col.metric(label, value)
    st.write("")

review_list, details, information = st.columns([1.15, 3.3, 1.15], gap="medium")
with review_list:
    st.markdown('<p class="panel-title">Recent reviews</p>', unsafe_allow_html=True)
    st.caption("Local browser session · not GitHub PRs")
    entries = st.session_state.history
    if not entries and active:
        entries = [
            {
                "review": active,
                "code": st.session_state.active_code,
                "base": st.session_state.active_base,
                "pr": st.session_state.active_pr,
            }
        ]
    if not entries:
        st.caption("No reviews yet. Submit a Python file to start.")
    for entry in entries:
        r = entry["review"]
        highest = next(
            (
                s
                for s in ("critical", "high", "medium", "low")
                if any(f.severity == s for f in r.findings)
            ),
            "none",
        )
        label = f"{r.id}\n{r.filename}\n{len(r.findings)} findings · {highest}\n{r.created_at[11:16]} UTC"
        if st.button(label, key="select-" + r.id, use_container_width=True):
            st.session_state.active = r
            st.session_state.active_pr = entry.get("pr")
            st.session_state.active_code = entry["code"]
            st.session_state.active_base = entry["base"]
            st.rerun()

with details:
    if not active:
        st.markdown(
            '<div class="summary"><div class="eyebrow">Ready for review</div>'
            "<h2>Understand your Python changes</h2><p>Run static checks, inspect source evidence, "
            "and optionally request contextual AI feedback.</p></div>",
            unsafe_allow_html=True,
        )
        st.info(
            "The editor contains a clearly illustrative sample. No review or check results are invented."
        )
    else:
        st.subheader(active.filename)
        st.caption(
            f"{active.id} · {active.created_at} · {active.elapsed_seconds:.2f}s static analysis"
        )
        tab_names = [
            "Overview",
            "Findings",
            "Code Diff",
            "Security",
            "Code Quality",
            "Suggestions",
        ]
        preferred = {
            "Security Analysis": "Security",
            "Code Quality": "Code Quality",
        }.get(page)
        if preferred:
            tab_names.remove(preferred)
            tab_names.insert(0, preferred)
        tabs = dict(zip(tab_names, st.tabs(tab_names)))
        with tabs["Overview"]:
            st.markdown(
                '<div class="summary"><div class="eyebrow">Static analysis summary</div><p>'
                + escape(active.summary)
                + "</p></div>",
                unsafe_allow_html=True,
            )
            if active.ai_summary:
                st.markdown("**AI-generated summary · unverified**")
                st.text(active.ai_summary)
            else:
                st.caption(
                    "AI summary unavailable. " + active.status.get("AI", "disabled")
                )
            if st.session_state.active_pr:
                bundle = st.session_state.active_pr
                st.text(bundle.metadata["title"])
                st.link_button("Open original PR", bundle.url)
                paths = [file.path for file in bundle.files if file.code]
                if paths:
                    selected_path = st.selectbox("PR source file", paths)
                    st.code(
                        next(
                            file.code
                            for file in bundle.files
                            if file.path == selected_path
                        ),
                        language="python",
                        line_numbers=True,
                    )
                for file in bundle.files:
                    if file.skip_reason:
                        st.text(file.path + ": " + file.skip_reason)
                if bundle.metadata.get("file_list_truncated"):
                    st.warning(
                        "GitHub file listing is capped at 100 files; this PR review is partial."
                    )
            else:
                st.code(
                    st.session_state.active_code, language="python", line_numbers=True
                )
            with st.expander("Extracted Python structure"):
                st.json(active.structure)
        with tabs["Findings"]:
            f1, f2 = st.columns(2)
            severity = f1.multiselect(
                "Severity",
                ["critical", "high", "medium", "low"],
                default=["critical", "high", "medium", "low"],
            )
            categories = f2.multiselect(
                "Category",
                [
                    "bug",
                    "security",
                    "quality",
                    "maintainability",
                    "performance",
                    "testing",
                ],
                default=[
                    "bug",
                    "security",
                    "quality",
                    "maintainability",
                    "performance",
                    "testing",
                ],
            )
            selected = [
                f
                for f in active.findings
                if f.severity in severity and f.category in categories
            ]
            st.caption(
                f"{len(selected)} matching findings. Static matches and AI hypotheses are labeled separately."
            )
            for f in selected:
                finding_card(f)
        with tabs["Code Diff"]:
            previous = st.session_state.active_base
            if st.session_state.active_pr:
                files = [
                    file for file in st.session_state.active_pr.files if file.patch
                ]
                if files:
                    selected_patch = st.selectbox(
                        "Changed-file diff", [file.path for file in files]
                    )
                    st.code(
                        next(
                            file.patch for file in files if file.path == selected_patch
                        ),
                        language="diff",
                    )
                else:
                    st.info("GitHub did not provide a diff for these files.")
            elif previous:
                diff = "\n".join(
                    difflib.unified_diff(
                        previous.splitlines(),
                        st.session_state.active_code.splitlines(),
                        fromfile="previous.py",
                        tofile=active.filename,
                        lineterm="",
                    )
                )
                st.code(
                    diff or "No changes between supplied versions.", language="diff"
                )
            else:
                st.info(
                    "No previous version supplied. This is a complete-file review, not a fetched PR diff."
                )
        with tabs["Security"]:
            st.warning(
                "Security tool signals indicate potential weaknesses, not confirmed exploitable vulnerabilities."
            )
            findings = [f for f in active.findings if f.category == "security"]
            if not findings:
                st.caption(
                    "No security findings from the checks that completed. This does not prove security."
                )
            for f in findings:
                finding_card(f)
        with tabs["Code Quality"]:
            findings = [
                f
                for f in active.findings
                if f.category in ("quality", "maintainability", "bug", "performance")
            ]
            if not findings:
                st.caption("No matching code-quality findings.")
            for f in findings:
                finding_card(f)
        with tabs["Suggestions"]:
            st.caption(
                "Suggestions require human verification. No fixes are applied or executed."
            )
            for f in active.findings:
                st.markdown(f"**{f.source} · line {f.line_start}**")
                st.text(f.suggested_fix)
            st.text(active.status.get("AI", "AI disabled"))
        if st.session_state.active_pr:
            bundle = st.session_state.active_pr
            with st.expander("Optional: publish selected review comments"):
                st.caption(
                    "This posts a COMMENT review, never an approval or merge. "
                    "A GitHub token with PR-write permission is required."
                )
                choices = {f.id: f for f in active.findings}
                chosen = st.multiselect(
                    "Findings to publish",
                    list(choices),
                    format_func=lambda ident: choices[ident].filename
                    + ":"
                    + str(choices[ident].line_start)
                    + " "
                    + choices[ident].title,
                )
                for ident in chosen:
                    finding = choices[ident]
                    st.text(
                        finding.title
                        + "\n"
                        + finding.explanation
                        + "\nSuggested improvement: "
                        + finding.suggested_fix
                    )
                publish_code = github_publish_code()
                entered_code = (
                    st.text_input("Publishing access code", type="password")
                    if publish_code
                    else ""
                )
                if not publish_code:
                    st.caption(
                        "Server publishing is disabled. An owner must configure GITHUB_TOKEN and "
                        "GITHUB_PUBLISH_CODE to enable this optional action."
                    )
                allowed = bool(publish_code) and hmac.compare_digest(
                    entered_code, publish_code or ""
                )
                authorized = st.checkbox(
                    "I authorize posting these selected comments to " + bundle.url,
                    key="authorize-" + bundle.head_sha + str(bundle.number),
                )
                if st.button(
                    "Publish selected PR comments",
                    disabled=not authorized or not chosen or not allowed,
                ):
                    try:
                        response = GitHubClient(token=github_token()).publish(
                            bundle, chosen, authorized=authorized
                        )
                        st.success(
                            "GitHub accepted the user-authorized review comments."
                        )
                        if isinstance(response, dict) and response.get(
                            "html_url", ""
                        ).startswith("https://github.com/"):
                            st.link_button(
                                "View published review", response["html_url"]
                            )
                    except ValueError as error:
                        st.error(str(error))
        a, b = st.columns(2)
        a.download_button(
            "Download JSON",
            active.model_dump_json(indent=2),
            f"{active.id}.json",
            "application/json",
            use_container_width=True,
        )
        b.download_button(
            "Download PDF",
            review_pdf(active),
            f"{active.id}.pdf",
            "application/pdf",
            use_container_width=True,
        )

with information:
    st.markdown('<p class="panel-title">Review information</p>', unsafe_allow_html=True)
    if active:
        st.caption("AUTOMATED CHECKS")
        for tool, status in active.status.items():
            st.text(f"{tool}: {status}")
        st.divider()
        st.caption("SEVERITY SUMMARY")
        counts = Counter(f.severity for f in active.findings)
        for severity in ("critical", "high", "medium", "low"):
            st.markdown(
                f'<span class="pill {severity}">{severity.upper()}: {counts[severity]}</span>',
                unsafe_allow_html=True,
            )
        st.divider()
        st.caption("METADATA")
        if st.session_state.active_pr:
            meta = st.session_state.active_pr.metadata
            st.text("Changed files: " + str(meta["changed_files"]))
            st.text("Author: " + meta["author"])
            st.text("Requested reviewers: " + (", ".join(meta["reviewers"]) or "none"))
            st.text("Assignees: " + (", ".join(meta["assignees"]) or "none"))
            st.text("Branches: " + meta["head_branch"] + " -> " + meta["base_branch"])
            st.text("Head commit: " + meta["head_commit"])
            st.text("Labels: " + (", ".join(meta["labels"]) or "none"))
        else:
            st.text("Changed files: 1 (submitted source)")
            st.text("Author / reviewers / assignees: not provided")
            st.text("Branch / commit: not provided")
            st.text("Labels: local Python review")
        st.caption("Check completion is not the same as checks finding no issues.")
    else:
        st.caption(
            "Check results appear after a real review. GitHub metadata is unavailable."
        )
