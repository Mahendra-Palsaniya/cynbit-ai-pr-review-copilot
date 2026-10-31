# AI Opportunity Report
## Cynbit AI PR Review Copilot

Prepared for the Cynbit assessment | 31 October 2026

### Executive assessment

A code-review assistant is a plausible opportunity for a company working in custom software and AI automation. The delivered prototype demonstrates deterministic Python checks with optional AI explanations. It does not establish demand, financial return, or improved developer performance. Cynbit has not supplied internal workflow data or endorsed this proposal.

### Evidence and fit

Cynbit's public website describes AI automation, custom software development, SaaS platforms and cloud systems. It also lists Cynbit Studio as career intelligence and Revio as an AI review assistant. The word review alone does not establish that Revio reviews source code. This proposal must be validated against existing products to avoid duplication. Source: https://www.cynbit.in/ (accessed 31 October 2026). Website statements are company marketing claims, not independently verified operating results.

### Candidate opportunities

| Opportunity | Prototype feasibility | Data needs | Proposed value | Main uncertainty |
|---|---|---|---|---|
| PR review copilot | High for Python snippets | Approved source and reviewer labels | Earlier feedback and explanations | False-positive burden and workflow fit |
| Documentation assistant | High | Approved repositories and style guides | Less repetitive writing | Factual correctness and maintenance |
| Test suggestion assistant | Medium | Code and test history | Edge-case discovery | Executability and meaningful assertions |
| Support assistant | Medium | Curated support knowledge | Faster initial responses | Retrieval quality and escalation |

These are qualitative judgments for project selection, not measured rankings. PR review was selected because it supports a reproducible offline baseline and a small demonstrable interface without private company data.

### Users and workflow

A developer pastes one complete Python file. The service checks syntax, runs Ruff and Bandit, adds AST findings, and displays structured feedback. A reviewer decides whether each finding is relevant. With explicit consent and a configured key, an LLM explains existing findings. The submitted file is never executed. Current functionality is source review; automated pull-request ingestion is future scope.

### Proposed benefits and validation

Earlier feedback, more consistent triage, and explanations for junior developers are hypotheses. No time savings, defect reduction, revenue impact or ROI has been measured. An illustrative model is net hours saved = reviews per month multiplied by minutes saved per review divided by 60, minus triage and maintenance hours. All inputs must be collected before calculating a company-specific value.

Run a two-week opt-in pilot with approved non-sensitive repositories. Establish a manual baseline, randomize comparable tasks with/without assistance, and measure median reviewer time, accepted findings, false positives, escaped defects and user satisfaction. Log rule IDs and acceptance decisions rather than raw code where possible. Pre-register a provisional go/no-go target: at least 80% actionable findings and a 15% reduction in review time with no increase in escaped defects. Those targets are proposed, not achieved; a small pilot may not have statistical power to establish defect effects.

### Demonstrated results

On 12 hand-authored synthetic examples: 11 exact rule/line true positives, no extra findings, and one deliberately included semantic miss. Precision was 100%, recall 91.7%, and median local latency approximately 1.13 seconds. Seventeen automated tests passed. This demonstrates plumbing and selected rule behavior, not broad accuracy or business benefit. LLM output quality was not evaluated; no key was used.

### Risks and decision

Incorrect/missing findings require human review. Confidential source requires a clear provider-processing decision. Prompt injection is mitigated by treating code as data and giving the model no tools, but prompt wording is not a complete security boundary. Public deployment needs access controls, resource limits and abuse protection. Begin with a private static-only pilot, add consented AI explanations only after privacy review, and expand to real PR context only if the pilot establishes value.

### Sources

- Cynbit public company website: https://www.cynbit.in/
- Prototype evidence: ../evaluation/results.json and ../evaluation/tests.xml
- Technical tool references: https://docs.astral.sh/ruff/configuration/ and https://bandit.readthedocs.io/en/latest/man/bandit.html
