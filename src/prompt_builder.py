"""Builds the Devin prompts for the fixer and reviewer sessions."""
import os
from dotenv import load_dotenv

load_dotenv()

GITHUB_REPO = os.getenv("GITHUB_REPO", "")


def build_fixer_prompt(issue: dict) -> str:
    """Return the prompt instructing Devin to fix the given GitHub issue."""
    number = issue["number"]
    title = issue["title"]
    html_url = issue["html_url"]
    body = issue.get("body") or ""
    short_title = title[:60]
    branch = f"autofix/issue-{number}"

    return f"""You are an automated software engineer working on the GitHub repository
https://github.com/{GITHUB_REPO}

Please fix the following issue end-to-end.

Issue #{number}: {title}
URL: {html_url}

Issue body:
---
{body}
---

Required steps:
1. Clone or open the repository at https://github.com/{GITHUB_REPO}.
2. Create a new branch named: {branch}
3. Investigate the issue and make the minimum set of code changes needed to fix it.
4. If practical, run the relevant tests to confirm your fix.
5. Commit the changes with this message:
   fix: resolve issue #{number} - {short_title}
6. Push the branch to origin.
7. Open a pull request targeting the master branch with:
   - PR title: fix: issue #{number} - {short_title}
   - PR body must include the line: Closes #{number}
   - PR body must include a "## Summary" section describing the change.

Rules:
- Change only what is necessary to fix this specific issue.
- Do not perform any unrelated refactoring, formatting changes, or cleanup.
- If you are blocked or cannot safely make a fix, stop and post a comment on
  issue #{number} explaining exactly why you are blocked.
"""


def build_reviewer_prompt(pr_url: str, pr_diff: str, original_issue: dict) -> str:
    """Return the prompt instructing Devin to review the fixer's PR."""
    number = original_issue["number"]
    title = original_issue["title"]
    body = original_issue.get("body") or ""
    body_excerpt = body[:500]
    diff_excerpt = (pr_diff or "")[:4000]

    return f"""You are a senior software engineer performing a code review on an
automated pull request. Be rigorous, fair, and concise.

Original issue #{number}: {title}
Issue body (first 500 chars):
{body_excerpt}

Pull request to review: {pr_url}

--- DIFF START ---
{diff_excerpt}
--- DIFF END ---

Review checklist - please consider each item carefully:
1. Does the change actually fix the issue described above?
2. Are there any bugs, logic errors, or edge cases missed?
3. What is the regression risk for other parts of the codebase?
4. Is the change minimal and focused, or does it include unrelated edits?
5. Is the PR description clear and does it correctly close the issue?

After completing your review you MUST post a single GitHub review comment on
the pull request at {pr_url}. The comment MUST follow this exact format:

## Automated Review by Devin
**Verdict:** APPROVED / CHANGES_REQUESTED / NEEDS_HUMAN
**Summary:** one sentence
**Checklist:**
- Fixes the issue: YES/NO
- No regressions introduced: YES/NO/UNCERTAIN
- Change is minimal and focused: YES/NO
**Reasoning:** 2-3 sentences

Pick exactly one Verdict value. Replace the placeholder text with your actual
findings. Do not add additional sections.
"""
