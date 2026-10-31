# Deployment status and runbook

31 October 2026

Local implementation, lint, security scan and 17 tests verified. Evaluation results are committed separately from proposed benefits. Private repository creation was confirmed through GitHub metadata. Remote push and hosted availability require independent confirmation; no live URL is claimed here.

Render MCP workspace listing failed with Transport closed. Reconnect Render in Codex, then list workspaces and identify the intended workspace before creating a service. No paid service is authorized by this runbook.

Once access is restored, create a Python web service from the repository main branch, build with `pip install -r requirements.txt`, start with `python -m streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true`, set Python 3.11, use health path `/_stcore/health`, and leave OPENAI_API_KEY unset. Select only an explicitly approved plan. If the private repo is unavailable, authorize this repository in the hosting provider's GitHub integration rather than making it public as a workaround.

Verify a successful terminal deploy state, HTTP health response, UI review of a sample, JSON download and no-key behavior. Record actual URL, deploy ID and timestamp only after these checks. Re-run checks after any deployment-specific changes. For rollback, select the preceding verified commit and redeploy through the provider.

Never store keys in Git, screenshots, deployment commands or report artifacts. Configure optional credentials in provider secret settings. Authentication and rate/concurrency controls remain prerequisites for sustained public use.
