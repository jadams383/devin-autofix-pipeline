"""Client for the GitHub REST API v3."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
BASE_URL = "https://api.github.com"


def _headers(accept: str = "application/vnd.github+json") -> dict:
    """Build the standard GitHub auth + version headers."""
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_issue(issue_number: int) -> dict:
    """Fetch a GitHub issue by number from the configured repository."""
    url = f"{BASE_URL}/repos/{GITHUB_REPO}/issues/{issue_number}"
    resp = requests.get(url, headers=_headers())
    resp.raise_for_status()
    return resp.json()


def post_issue_comment(issue_number: int, body: str) -> dict:
    """Post a new comment on the given issue and return the response."""
    url = f"{BASE_URL}/repos/{GITHUB_REPO}/issues/{issue_number}/comments"
    resp = requests.post(url, json={"body": body}, headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_pr_diff(pr_number: int) -> str:
    """Return the raw unified diff for a PR, or an empty string on error."""
    try:
        url = f"{BASE_URL}/repos/{GITHUB_REPO}/pulls/{pr_number}"
        resp = requests.get(url, headers=_headers(accept="application/vnd.github.diff"))
        resp.raise_for_status()
        return resp.text
    except Exception:
        return ""
