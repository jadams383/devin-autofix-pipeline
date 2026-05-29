"""Two-session Devin pipeline: fixer creates PR, reviewer reviews it."""
import os
import re
import threading
import time
import traceback
from dotenv import load_dotenv

from src import db
from src.devin_client import create_session, poll_until_done, send_message
from src.github_client import get_issue, post_issue_comment, get_pr_diff
from src.prompt_builder import build_fixer_prompt, build_reviewer_prompt

load_dotenv()

GITHUB_REPO = os.getenv("GITHUB_REPO", "")


def extract_verdict(session: dict) -> str:
    """Scan reviewer-side text fields for the exact ``**Verdict:** X`` marker.

    The reviewer prompt instructs Devin to emit a single line of the form
    ``**Verdict:** APPROVED`` (or ``CHANGES_REQUESTED`` / ``NEEDS_HUMAN``).
    Matching that exact pattern avoids false positives from review prose like
    "The first review requested changes" or "not APPROVED" that would otherwise
    cause a stale CHANGES_REQUESTED to override a real APPROVED verdict.
    """
    verdict_re = re.compile(
        r'\*\*Verdict:\*\*\s*(APPROVED|CHANGES_REQUESTED|NEEDS_HUMAN)'
    )

    def _candidate_strings():
        for i, msg in enumerate(session.get("messages", []) or []):
            if not isinstance(msg, dict):
                continue
            for key in ("message", "text", "content"):
                val = msg.get(key)
                if isinstance(val, str) and val:
                    yield f"messages[{i}].{key}", val
        structured = session.get("structured_output")
        if isinstance(structured, dict):
            for k, v in structured.items():
                if isinstance(v, str) and v:
                    yield f"structured_output.{k}", v
        elif isinstance(structured, str) and structured:
            yield "structured_output", structured

    for location, text in _candidate_strings():
        match = verdict_re.search(text)
        if match:
            verdict = match.group(1)
            print(f"[verdict] found {verdict} in {location}")
            return verdict

    print("[verdict] no verdict keyword found; returning UNKNOWN")
    return "UNKNOWN"


def _reviewer_db_status(reviewer_status: str, reviewer_result: dict) -> str:
    """Map Devin's terminal reviewer status to the value we record in the DB."""
    if reviewer_status == "expired" or bool(reviewer_result.get("timed_out")):
        return "failed"
    if reviewer_status in ("blocked", "finished"):
        return "completed"
    return reviewer_status or "completed"


def extract_reasoning(session: dict, limit: int = 500) -> str:
    """Return up to ``limit`` chars of the last reviewer-style 'Reasoning:' block."""
    found = ""
    for msg in session.get("messages", []) or []:
        text = msg.get("message") or ""
        idx = text.rfind("Reasoning:")
        if idx != -1:
            found = text[idx + len("Reasoning:"):].strip()
    return found[:limit] if found else "(no reasoning extracted from reviewer messages)"


def run_pipeline(issue_number: int, trigger_type: str = "manual") -> None:
    """Execute the full fixer -> reviewer pipeline for one issue."""
    run_id = None
    try:
        print(f"[pipeline] starting run for issue #{issue_number} (trigger={trigger_type})")

        # fetch issue
        issue = get_issue(issue_number)
        title = issue["title"]
        html_url = issue["html_url"]
        print(f"[pipeline] fetched issue #{issue_number}: {title}")

        # create DB run
        run_id = db.create_run(issue_number, title, html_url, trigger_type)
        print(f"[pipeline] created db run id={run_id}")

        # SESSION 1: FIXER
        print(f"[pipeline] dispatching fixer session for issue #{issue_number}")
        fixer_prompt = build_fixer_prompt(issue)
        fixer_resp = create_session(
            prompt=fixer_prompt,
            title=f"[Fixer] Issue #{issue_number}: {title[:50]}",
            tags=[f"issue-{issue_number}", "fixer", "autofix-pipeline"],
        )
        fixer_session_id = fixer_resp.get("session_id")
        fixer_session_url = fixer_resp.get("url")
        db.update_fixer(run_id, fixer_session_id, fixer_session_url)
        post_issue_comment(
            issue_number,
            f"🤖 Devin Fixer session dispatched: {fixer_session_url}\n\nWorking on a fix automatically.",
        )
        print(f"[pipeline] fixer dispatched: session={fixer_session_id} url={fixer_session_url}")

        fixer_result = poll_until_done(fixer_session_id)
        fixer_status = fixer_result.get("status_enum")
        pr_obj = fixer_result.get("pull_request") or {}
        pr_url = pr_obj.get("url") if isinstance(pr_obj, dict) else None
        print(f"[pipeline] fixer terminal status={fixer_status} pr_url={pr_url}")

        # If Devin is blocked without producing a PR, nudge it to continue and
        # poll once more before deciding whether this run actually failed.
        if fixer_status == "blocked" and not pr_url:
            print(f"[pipeline] fixer blocked without PR; sending unblock message and re-polling")
            send_message(
                fixer_session_id,
                "Please continue and complete the task. Create the pull request now and finish the session.",
            )
            time.sleep(15)
            fixer_result = poll_until_done(fixer_session_id)
            fixer_status = fixer_result.get("status_enum")
            pr_obj = fixer_result.get("pull_request") or {}
            pr_url = pr_obj.get("url") if isinstance(pr_obj, dict) else None
            print(f"[pipeline] fixer terminal status (after unblock)={fixer_status} pr_url={pr_url}")

        fixer_done = (fixer_status in ("finished", "blocked")) and bool(pr_url)
        timed_out = bool(fixer_result.get("timed_out"))

        if fixer_status == "expired" or (fixer_status == "blocked" and not pr_url) or timed_out:
            reason = f"fixer status={fixer_status}, pr_url={pr_url}, timed_out={timed_out}"
            db.update_fixer_done(run_id, "failed")
            db.update_failure(run_id, reason)
            post_issue_comment(
                issue_number,
                f"❌ Devin Fixer session did not produce a PR. Status: {fixer_status}. "
                f"Session: {fixer_session_url}",
            )
            print(f"[pipeline] FAILURE: {reason}")
            return

        if not fixer_done:
            # Non-terminal status (e.g. None from initialization) with no PR -
            # not an explicit failure, but nothing to review either.
            db.update_fixer_done(run_id, fixer_status or "incomplete")
            post_issue_comment(
                issue_number,
                f"⚠️ Devin Fixer has not produced a PR yet. Status: {fixer_status}. "
                f"Session: {fixer_session_url}",
            )
            print(f"[pipeline] no PR produced (status={fixer_status}); skipping reviewer")
            return

        print(f"[pipeline] fixer SUCCESS status={fixer_status} pr_url={pr_url}")
        db.update_fixer_done(run_id, "success", pr_url)
        post_issue_comment(
            issue_number,
            f"✅ Fixer opened PR: {pr_url}\n\nDispatching Reviewer session now...",
        )

        # SESSION 2: REVIEWER
        print(f"[pipeline] dispatching reviewer session for PR {pr_url}")
        match = re.search(r"/pull/(\d+)", pr_url)
        pr_number = int(match.group(1)) if match else None
        try:
            pr_diff = get_pr_diff(pr_number) if pr_number is not None else ""
        except Exception:
            pr_diff = ""

        reviewer_prompt = build_reviewer_prompt(pr_url, pr_diff, issue)
        reviewer_resp = create_session(
            prompt=reviewer_prompt,
            title=f"[Reviewer] Issue #{issue_number}: {title[:50]}",
            tags=[f"issue-{issue_number}", "reviewer", "autofix-pipeline"],
        )
        reviewer_session_id = reviewer_resp.get("session_id")
        reviewer_session_url = reviewer_resp.get("url")
        db.update_reviewer(run_id, reviewer_session_id, reviewer_session_url)
        post_issue_comment(
            issue_number,
            f"🔍 Devin Reviewer session dispatched: {reviewer_session_url}",
        )
        print(f"[pipeline] reviewer dispatched: session={reviewer_session_id} url={reviewer_session_url}")

        reviewer_result = poll_until_done(reviewer_session_id)
        reviewer_status = reviewer_result.get("status_enum")
        verdict = extract_verdict(reviewer_result)
        db_reviewer_status = _reviewer_db_status(reviewer_status, reviewer_result)
        print(f"[pipeline] reviewer terminal status={reviewer_status} (db={db_reviewer_status}) verdict={verdict}")

        # Verdict routing: re-queue fixer / approve / hand off to human.
        # CHANGES_REQUESTED is checked first because prose like "not APPROVED" can
        # appear inside a change-request review and we never want it to win.
        if verdict == "CHANGES_REQUESTED":
            # Defensive guard: only re-queue on a genuine CHANGES_REQUESTED
            # verdict so a false-positive extraction can never reach this code.
            if verdict != "CHANGES_REQUESTED":
                pass  # fall through to APPROVED or NEEDS_HUMAN handling
            db.update_reviewer_done(run_id, db_reviewer_status, "CHANGES_REQUESTED")
            post_issue_comment(
                issue_number,
                "🔄 Reviewer requested changes. Re-queuing Fixer session with feedback...",
            )

            # STEP 1: extract reviewer reasoning
            reviewer_reasoning = extract_reasoning(reviewer_result)

            # STEP 2: create fixer retry session
            retry_prompt = (
                f"You previously opened PR {pr_url} for issue #{issue_number} but a "
                f"code review requested changes. Here is the reviewer feedback:\n\n"
                f"{reviewer_reasoning}\n\n"
                f"Please address the reviewer feedback by updating the existing PR. "
                f"Push your changes to the same branch autofix/issue-{issue_number}.\n"
                f"Do not open a new PR - update the existing one at {pr_url}."
            )
            retry_resp = create_session(
                prompt=retry_prompt,
                title=f"[Fixer-Retry] Issue #{issue_number}: {title[:50]}",
                tags=[f"issue-{issue_number}", "fixer-retry", "autofix-pipeline"],
            )
            retry_session_id = retry_resp.get("session_id")
            retry_session_url = retry_resp.get("url")
            db.update_retry_fixer(run_id, retry_session_id, retry_session_url)
            print(f"[pipeline] fixer-retry dispatched: session={retry_session_id} url={retry_session_url}")

            # STEP 3: poll fixer retry until done
            retry_result = poll_until_done(retry_session_id)
            retry_status = retry_result.get("status_enum")

            # STEP 4: extract new PR url, fall back to original
            new_pr_obj = retry_result.get("pull_request") or {}
            new_pr_url = new_pr_obj.get("url") if isinstance(new_pr_obj, dict) else None
            if not new_pr_url:
                new_pr_url = pr_url
            print(f"[pipeline] fixer-retry terminal status={retry_status} new_pr_url={new_pr_url}")

            # STEP 5: record retry session + mark fixer done with the (possibly updated) PR
            db.update_fixer(run_id, retry_session_id, retry_session_url)
            db.update_fixer_done(run_id, "success", new_pr_url)

            # STEP 6: announce retry complete and that a second review is coming
            post_issue_comment(
                issue_number,
                f"🔁 Fixer retry complete. Updated PR: {new_pr_url}\nDispatching second review...",
            )

            # STEP 7: dispatch a new reviewer session against the updated PR
            new_match = re.search(r"/pull/(\d+)", new_pr_url)
            new_pr_number = int(new_match.group(1)) if new_match else None
            try:
                new_pr_diff = get_pr_diff(new_pr_number) if new_pr_number is not None else ""
            except Exception:
                new_pr_diff = ""

            new_reviewer_prompt = (
                "NOTE: This is a second review. The first review requested changes. "
                "The fixer has addressed that feedback. Please review the updated PR."
                + "\n\n"
                + build_reviewer_prompt(new_pr_url, new_pr_diff, issue)
            )
            new_reviewer_resp = create_session(
                prompt=new_reviewer_prompt,
                title=f"[Reviewer-2] Issue #{issue_number}: {title[:50]}",
                tags=[f"issue-{issue_number}", "reviewer-2", "autofix-pipeline"],
            )
            new_reviewer_session_id = new_reviewer_resp.get("session_id")
            new_reviewer_session_url = new_reviewer_resp.get("url")

            # STEP 8: record the new reviewer session
            db.update_reviewer(run_id, new_reviewer_session_id, new_reviewer_session_url)
            print(
                f"[pipeline] reviewer-2 dispatched: session={new_reviewer_session_id} "
                f"url={new_reviewer_session_url}"
            )

            # STEP 9: poll the new reviewer until done
            new_reviewer_result = poll_until_done(new_reviewer_session_id)
            new_reviewer_status = new_reviewer_result.get("status_enum")

            # STEP 10: extract the second verdict
            new_verdict = extract_verdict(new_reviewer_result)
            new_db_reviewer_status = _reviewer_db_status(new_reviewer_status, new_reviewer_result)
            print(
                f"[pipeline] reviewer-2 terminal status={new_reviewer_status} "
                f"(db={new_db_reviewer_status}) verdict={new_verdict}"
            )

            # STEP 11: record the second reviewer outcome
            print(f"[pipeline] updating verdict to {new_verdict} for run_id={run_id}")
            db.update_reviewer_done(run_id, new_db_reviewer_status, new_verdict)
            print(f"[pipeline] updating verdict to {new_verdict} for run_id={run_id}")

            # STEP 12: post the second-review verdict back on the issue
            post_issue_comment(
                issue_number,
                f"✅ Second review complete.\nVerdict: {new_verdict}\nPR: {new_pr_url}\n"
                f"Session: {new_reviewer_session_url}",
            )

            # STEP 13: final log line
            print(
                f"[pipeline] DONE issue #{issue_number} retry-verdict={new_verdict} "
                f"pr={new_pr_url}"
            )
            return

        if verdict == "APPROVED":
            db.update_reviewer_done(run_id, db_reviewer_status, "APPROVED")
            post_issue_comment(
                issue_number,
                f"✅ Reviewer verdict: APPROVED\n\nPR {pr_url} has been reviewed and "
                f"approved by the automated reviewer. Ready for final human merge.",
            )
            print(f"[pipeline] DONE issue #{issue_number} verdict=APPROVED pr={pr_url}")
            return

        # NEEDS_HUMAN or UNKNOWN
        db.update_reviewer_done(run_id, db_reviewer_status, verdict)
        post_issue_comment(
            issue_number,
            f"🧑‍💻 Reviewer verdict: {verdict}\n\nThis issue requires human review. "
            f"PR: {pr_url}\nReviewer session: {reviewer_session_url}",
        )
        print(f"[pipeline] DONE issue #{issue_number} verdict={verdict} (human handoff)")

    except Exception as e:
        traceback.print_exc()
        if run_id is not None:
            try:
                db.update_failure(run_id, str(e))
            except Exception:
                traceback.print_exc()


def dispatch_in_background(issue_number: int, trigger_type: str = "manual") -> None:
    """Spawn the pipeline for an issue in a daemon thread so the caller returns immediately."""
    print(f"[dispatch] launching background pipeline for issue #{issue_number} (trigger={trigger_type})")
    thread = threading.Thread(
        target=run_pipeline,
        args=(issue_number, trigger_type),
        daemon=True,
    )
    thread.start()
