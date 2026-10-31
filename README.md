# Cynbit AI PR Review Copilot

A Python and Streamlit assessment prototype for reviewing complete Python source files using Ruff, Bandit, custom AST checks, and optional OpenAI commentary. Independent assessment work; not an official Cynbit product.

**Live demo:** https://cynbit-ai-pr-review-copilot.streamlit.app/

## Run from scratch

Requires Python 3.11 and internet access for dependency installation.

```powershell
git clone https://github.com/Mahendra-Palsaniya/cynbit-ai-pr-review-copilot.git
cd cynbit-ai-pr-review-copilot
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m streamlit run app.py
```

On Linux/macOS replace `.venv/Scripts/python` with `.venv/bin/python`. Paste either sample in `samples/`, press Review code, inspect tool status and findings, and download the JSON report.

## What is implemented

- One complete Python file per review; 50,000 UTF-8 byte limit.
- Ruff E4/E7/E9/F lint checks, Bandit security checks and AST mutable-default/bare-except checks.
- Validated finding records containing tool, rule, line, severity, message and manual remediation guidance.
- Per-tool completion status; failures preserve other findings and explicitly mark incomplete results.
- Optional LLM explanations of existing findings. Without a key, deterministic checks remain fully usable.
- Streamlit UI, downloadable JSON, unit/integration tests, synthetic labeled evaluation, CI configuration and two reports.

## Optional AI

Configure `OPENAI_API_KEY` through your operating system or hosting provider's secret settings. Do not paste keys into the app, chat, source files or GitHub. `OPENAI_MODEL` optionally overrides `gpt-4.1-mini`; model access depends on your account. Restart the app after configuring secrets. Enable the explicit source-sharing checkbox for each review. The source and findings are then sent to OpenAI; `store=False` is requested, but this is not a guarantee of zero provider retention. Review the provider's data policy before using private source. Failures return generic feedback without exposing raw exception text. No live API call or LLM-quality measurement was performed for the delivered evaluation.

## Verify

```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check app.py copilot tests evaluate.py
.venv/Scripts/python -m bandit -r copilot app.py -q
.venv/Scripts/python evaluate.py
```

Measured on 31 October 2026: 17 tests passed; Ruff and Bandit checks passed. The 12 authored synthetic evaluation cases yielded 11 true positives, 0 false positives and 1 false negative: precision 100%, recall 91.7%, median 1.13 seconds on the recorded Windows/Python environment. Exact unique (rule ID, line) matching counts overlapping tools as separate rule findings. This is a tiny fixture set, not a held-out benchmark. The missed case is division by zero for an empty collection. See `evaluation/results.json` for raw records and `evaluation/tests.xml` for test evidence. Timings vary by environment; rerunning replaces local evaluation results.

## Safety and limits

Submitted code is never executed or imported. Only fixed analyzer modules are launched with argument lists, no shell, isolated temporary paths and 15-second tool timeouts. Temporary source is deleted on normal completion, but abrupt process termination can leave temporary files. Ruff configuration is isolated; Bandit ignores submitted `nosec` comments. Findings may contain source identifiers: treat exported reports as potentially sensitive. No application code logging or code database is configured; hosting logs and browser/session memory have separate lifecycles.

This is a trusted-user prototype, not a hardened public service: input size and subprocess timeouts do not impose a hard memory/CPU limit on in-process parsing. Add process/container quotas, authentication, rate limiting, concurrency limits and data-retention controls before broad exposure. Do not provide a shared paid API key on an unauthenticated public demo. Review all suggested fixes manually. Severity is a triage hint; all Ruff findings currently map to low severity. No PR fetching, unified-diff support, automatic patches, GitHub comments, multi-file context, trained model, or guarantee of safe code is implemented. The product name describes its intended future workflow.

## Hosting on Streamlit Community Cloud

The owner selected Streamlit Community Cloud. In your workspace choose Create app, deploy from GitHub, select `Mahendra-Palsaniya/cynbit-ai-pr-review-copilot`, branch `main`, main file `app.py`, and Python 3.11 in Advanced settings. Leave secrets empty for the no-key demo, then deploy. Verify an actual review and JSON download before sharing the resulting URL. Live deployment verified on 31 October 2026: all three analyzers completed, JSON export contained F401/B307/MUTABLE_DEFAULT, and the no-key fallback preserved static results. See `docs/DEPLOYMENT.md` for status.

## Reports

- [AI Opportunity Report](docs/AI_OPPORTUNITY.md)
- [Technical Approach Report](docs/TECHNICAL_APPROACH.md)
- [AI Opportunity PDF](docs/AI_OPPORTUNITY.pdf)
- [Technical Approach PDF](docs/TECHNICAL_APPROACH.pdf)
- [Deployment and verification status](docs/DEPLOYMENT.md)

Pinned direct dependencies are supplied; transitive dependencies are not locked. No license grant is assumed; add your preferred license before external redistribution.

GitHub Actions passed on the initial implementation commit: https://github.com/Mahendra-Palsaniya/cynbit-ai-pr-review-copilot/actions/runs/41174769485
