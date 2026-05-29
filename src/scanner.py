"""Vulnerability scanner: discovers CVEs in the target repo and files them as GitHub issues."""
import json
import os
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def get_existing_issue_titles() -> set:
    """Return the lowercased titles of all existing issues so we can dedupe."""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
        resp = requests.get(
            url,
            params={"state": "all", "per_page": 100},
            headers=GITHUB_HEADERS,
        )
        resp.raise_for_status()
        return {(item.get("title") or "").lower() for item in resp.json()}
    except Exception as e:
        print(f"[scanner] error fetching existing issues: {e}")
        return set()


def create_github_issue(title: str, body: str, labels: list) -> dict:
    """Create a new GitHub issue with the given title, body, and labels."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
    payload = {"title": title, "body": body, "labels": labels}
    resp = requests.post(url, json=payload, headers=GITHUB_HEADERS)
    resp.raise_for_status()
    return resp.json()


def get_vulnerability_findings() -> list:
    """Return the hardcoded list of vulnerability findings discovered by our scan tools."""
    return [
        {
            "title": "[SECURITY] Upgrade flask to 3.1.3 - CVE-2026-27205",
            "severity": "HIGH",
            "body": """## Finding
pip-audit flagged `flask==2.3.3` with CVE-2026-27205 (GHSA-68rp-wp8r-4726).

Flask fails to set the `Vary: Cookie` header in certain session access patterns
(e.g. using Python's `in` operator on the session object). This can cause caching
proxies to serve session-specific responses to the wrong users.

Fixed in flask >= 3.1.3.

## Affected File
`requirements/base.txt` — `flask==2.3.3`

## Expected Fix
Upgrade `flask` to `>=3.1.3` in `requirements/base.txt`.

## Acceptance Criteria
- [ ] flask version bumped to >=3.1.3
- [ ] No Flask-related import errors introduced
- [ ] PR opened targeting master""",
        },
        {
            "title": "[SECURITY] Replace weak MD5 hash in hashing.py - B324",
            "severity": "HIGH",
            "body": """## Finding
Bandit flagged `superset/utils/hashing.py:34` with B324 (HIGH severity, HIGH confidence).
Use of weak MD5 hash for security. Consider usedforsecurity=False.

MD5 is a cryptographically broken hash algorithm.

## Affected File
`superset/utils/hashing.py` — line 34

## Expected Fix
Add `usedforsecurity=False` to the hashlib.md5() call:
  hashlib.md5(value, usedforsecurity=False)

## Acceptance Criteria
- [ ] MD5 usage at line 34 updated with usedforsecurity=False
- [ ] Existing tests still pass
- [ ] PR opened targeting master""",
        },
        {
            "title": "[SECURITY] Upgrade idna to 3.15 - CVE-2026-45409",
            "severity": "HIGH",
            "body": """## Finding
pip-audit flagged `idna==3.10` with CVE-2026-45409 (GHSA-65pc-fj4g-8rjx).

ReDoS vulnerability — specially crafted inputs to idna.encode() bypass
length rejection and consume excessive CPU, enabling DoS attacks.
Fixed in idna >= 3.15.

## Affected File
`requirements/base.txt` — `idna==3.10`

## Expected Fix
Bump `idna` to `>=3.15` in `requirements/base.txt`.

## Acceptance Criteria
- [ ] idna version bumped to >=3.15
- [ ] No import or encoding regressions
- [ ] PR opened targeting master""",
        },
        {
            "title": "[SECURITY] Replace unsafe yaml.load() with yaml.safe_load() - B506",
            "severity": "MEDIUM",
            "body": """## Finding
Bandit flagged `superset/examples/utils.py:261` with B506 (MEDIUM severity, HIGH confidence).
Use of unsafe yaml load. Allows instantiation of arbitrary objects.

yaml.load() without a safe Loader can deserialize arbitrary Python objects,
enabling remote code execution if YAML source is user-controlled.

## Affected File
`superset/examples/utils.py` — line 261

## Expected Fix
Replace:
  yaml.load(stream)
With:
  yaml.safe_load(stream)

## Acceptance Criteria
- [ ] yaml.load() replaced with yaml.safe_load() at line 261
- [ ] Functionality verified unchanged
- [ ] PR opened targeting master""",
        },
    ]


def run_scan() -> dict:
    """Run a full scan: enumerate findings, dedupe against existing issues, create new ones."""
    try:
        print(f"[scanner] Starting vulnerability scan of {GITHUB_REPO}")
        existing = get_existing_issue_titles()
        findings = get_vulnerability_findings()

        created = 0
        skipped = 0
        for finding in findings:
            title = finding["title"]
            body = finding["body"]
            if title.lower() in existing:
                print(f"[scanner] Skipping duplicate: {title}")
                skipped += 1
                continue
            issue = create_github_issue(title, body, ["autofix", "security"])
            number = issue.get("number")
            print(f"[scanner] Created issue #{number}: {title}")
            created += 1
            time.sleep(1)

        result = {"scanned": len(findings), "created": created, "skipped": skipped}
        print(f"[scanner] Scan complete: {result}")
        return result
    except Exception as e:
        print(f"[scanner] ERROR during scan: {e}")
        raise


if __name__ == "__main__":
    print(json.dumps(run_scan(), indent=2))
