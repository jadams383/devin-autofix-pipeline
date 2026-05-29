"""Registers a recurring Devin v3 schedule that runs the vulnerability scanner."""
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

DEVIN_API_KEY = os.getenv("DEVIN_API_KEY", "")
DEVIN_ORG_ID = os.getenv("DEVIN_ORG_ID", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

BASE_URL = f"https://api.devin.ai/v3/organizations/{DEVIN_ORG_ID}/schedules"
HEADERS = {
    "Authorization": f"Bearer {DEVIN_API_KEY}",
    "Content-Type": "application/json",
}

SCHEDULE_NAME = "superset-vulnerability-scanner"


def _build_scanner_prompt() -> str:
    """Build the Devin prompt that the scheduled session will run on each tick."""
    return f"""You are an autonomous security scanner running on a recurring schedule.
This is a fully automated task — no human review is needed.

1. Clone or access the repository at https://github.com/{GITHUB_REPO}.
2. Run `pip-audit` against `requirements/base.txt` to find vulnerable packages.
3. For each vulnerability found that has a CVE ID:
   a. Check the repository's GitHub issues to see whether an issue already
      exists for that CVE.
   b. If no existing issue is found, create a new GitHub issue with:
      - Title: "[SECURITY] Upgrade {{package}} - {{CVE}}"
      - Body: details of the finding, affected file, expected fix, and
        acceptance criteria.
      - Label: "autofix"
4. After processing all findings, report a summary of how many vulnerabilities
   were discovered, how many were skipped as duplicates, and how many new
   issues were created.

Operate fully autonomously. Do not pause for human input.
"""


def get_existing_schedule() -> dict:
    """Look up an existing Devin schedule by name; return it or None."""
    try:
        resp = requests.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []) or []:
            if item.get("name") == SCHEDULE_NAME:
                return item
        return None
    except Exception as e:
        print(f"[scheduler] error fetching existing schedules: {e}")
        return None


def create_scanner_schedule(cron: str = "0 9 * * 1-5") -> dict:
    """Create a new recurring Devin schedule that fires the scanner prompt."""
    payload = {
        "name": SCHEDULE_NAME,
        "prompt": _build_scanner_prompt(),
        "schedule_type": "recurring",
        "frequency": cron,
        "tags": ["vulnerability-scanner", "automated", "superset"],
        "notify_on": "failure",
    }
    try:
        resp = requests.post(BASE_URL, json=payload, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
        schedule_id = data.get("id") or data.get("schedule_id")
        print(f"[scheduler] Created Devin schedule: {schedule_id} (cron: {cron})")
        return data
    except Exception as e:
        print(f"[scheduler] error creating schedule: {e}")
        raise


def register_schedule(cron: str = "0 9 * * 1-5") -> dict:
    """Create the scanner schedule if it doesn't already exist; return whichever exists now."""
    existing = get_existing_schedule()
    if existing:
        existing_id = existing.get("id") or existing.get("schedule_id")
        print(f"[scheduler] Schedule already exists: {existing_id}")
        return existing
    return create_scanner_schedule(cron)


def get_schedule_status() -> dict:
    """Return the full paginated list of Devin schedules for this org."""
    try:
        resp = requests.get(BASE_URL, headers=HEADERS)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[scheduler] error fetching schedules: {e}")
        return {"error": str(e), "items": []}


if __name__ == "__main__":
    print(json.dumps(register_schedule(), indent=2, default=str))
