# Devin Autofix Pipeline

Autonomous vulnerability discovery and remediation using the Devin API.

## What this does

1. Scanner discovers real CVEs in Apache Superset using pip-audit and Bandit
2. Creates GitHub issues automatically with the `autofix` label
3. Webhook triggers Session 1 (Fixer) — Devin diagnoses and opens a PR
4. Session 2 (Reviewer) — second Devin session reviews the PR diff and
   posts a structured verdict (APPROVED / CHANGES_REQUESTED / NEEDS_HUMAN)
5. If CHANGES_REQUESTED — Session 3 (Fixer Retry) addresses the feedback,
   Session 4 (Reviewer 2) reviews again
6. Dashboard tracks every session, PR, verdict, and MTTR in real time

## Quickstart

    cp .env.example .env
    # Fill in DEVIN_API_KEY, DEVIN_ORG_ID, GITHUB_TOKEN,
    # GITHUB_REPO, GITHUB_WEBHOOK_SECRET

    docker compose up --build

    # Expose with ngrok for webhook:
    ngrok http 8000

    # Trigger the scanner:
    curl -X POST http://localhost:8000/scan

    # Manual trigger for a specific issue:
    curl -X POST http://localhost:8000/trigger/{issue_number}

## Architecture

- Trigger: GitHub webhook (issues.labeled = autofix)
- Scanner: pip-audit + Bandit findings → auto-creates GitHub issues
- Orchestrator: FastAPI + Python, Dockerized
- Agent layer: Devin API v1 — up to 4 sessions per issue with distinct roles
- Scheduler: Devin API v3 cron schedule (daily Mon-Fri 9am UTC)
- Observability: SQLite + live dashboard at localhost:8000

## Extending this

- Multi-repo support via org-level webhook
- Slack alerts on CHANGES_REQUESTED verdict
- Auto-merge on APPROVED + passing CI
- JIRA/Linear as trigger source
