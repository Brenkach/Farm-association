
## Quality and security checks

- Complexity: `radon cc -s -a .` and `flake8 --select=CCR --max-cognitive-complexity=15 routes.py`
- Tests: `pytest tests/ -v`
- SCA: `pip-audit -r requirements.txt`
- Secrets: `pre-commit install` once, then every commit runs `gitleaks protect --staged`. Full history: `gitleaks detect --source . --redact -v`
- Copy `.env.example` to `.env` and fill in real values locally (`.env` is git-ignored)
