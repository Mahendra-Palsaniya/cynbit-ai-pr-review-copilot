# Streamlit Community Cloud deployment

31 October 2026

The owner selected Streamlit Community Cloud and canceled Render deployment. No successful Render service creation was confirmed. The repository is public as explicitly requested by the owner.

Verified: local 17-test suite, Ruff and Bandit application scans, synthetic evaluation, successful initial Linux GitHub Actions run 41174769485, Git push, ZIP integrity, and visual PDF QA. Community Cloud deployment awaits a signed-in browser workspace. Do not claim a live URL before actual verification.

## Deployment settings

- Repository: Mahendra-Palsaniya/cynbit-ai-pr-review-copilot
- Branch: main
- Main file: app.py
- Python: 3.11 (Advanced settings)
- Secrets: leave empty; static review requires no key
- Dependencies: requirements.txt at repository root

After deployment, open the actual generated app URL, review the problematic sample, verify AST/Ruff/Bandit completed status, download the review JSON and inspect it. Test clean and invalid Python inputs. Confirm the no-key message if AI commentary is requested. Record the actual URL and successful verification time here. Community Cloud may sleep inactive apps; wake-up behavior is separate from application correctness.

Do not add a shared paid API key to the public demo without appropriate access and abuse controls. Optional API keys belong only in hosting secret settings; no credentials should be entered in the source or committed to Git. Submitted code is not executed. Resource isolation, authentication, rate limits and independent accuracy evaluation remain future hardening work.
