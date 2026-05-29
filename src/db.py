"""SQLite persistence layer for pipeline runs."""
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/sessions.db")


def _connect() -> sqlite3.Connection:
    """Open a SQLite connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _exec(sql: str, *args) -> None:
    """Run a single write statement inside its own connection and commit."""
    conn = _connect()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the data directory and the pipeline_runs table if missing."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    _exec(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_number INTEGER,
            issue_title TEXT,
            issue_url TEXT,
            trigger_type TEXT DEFAULT 'manual',
            fixer_session_id TEXT,
            fixer_session_url TEXT,
            retry_fixer_session_id TEXT,
            retry_fixer_session_url TEXT,
            reviewer_session_id TEXT,
            reviewer_session_url TEXT,
            fixer_status TEXT DEFAULT 'dispatched',
            reviewer_status TEXT,
            reviewer_verdict TEXT,
            pr_url TEXT,
            failure_reason TEXT,
            dispatched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            fixed_at DATETIME,
            reviewed_at DATETIME
        )
        """
    )


def create_run(issue_number: int, issue_title: str, issue_url: str, trigger_type: str = "manual") -> int:
    """Insert a new pipeline run row and return its id."""
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO pipeline_runs (issue_number, issue_title, issue_url, trigger_type)
            VALUES (?, ?, ?, ?)
            """,
            (issue_number, issue_title, issue_url, trigger_type),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_fixer(run_id: int, session_id: str, session_url: str) -> None:
    """Record the fixer Devin session id and URL on a run."""
    _exec(
        "UPDATE pipeline_runs SET fixer_session_id = ?, fixer_session_url = ? WHERE id = ?",
        session_id, session_url, run_id,
    )


def update_fixer_done(run_id: int, status: str, pr_url: str = None) -> None:
    """Mark the fixer phase complete with its status and any opened PR URL."""
    _exec(
        "UPDATE pipeline_runs SET fixer_status = ?, pr_url = ?, fixed_at = CURRENT_TIMESTAMP WHERE id = ?",
        status, pr_url, run_id,
    )


def update_retry_fixer(run_id: int, session_id: str, session_url: str) -> None:
    """Record the fixer-retry Devin session id and URL on a run."""
    _exec(
        "UPDATE pipeline_runs SET retry_fixer_session_id = ?, retry_fixer_session_url = ? WHERE id = ?",
        session_id, session_url, run_id,
    )


def update_reviewer(run_id: int, session_id: str, session_url: str) -> None:
    """Record the reviewer Devin session id and URL on a run."""
    _exec(
        "UPDATE pipeline_runs SET reviewer_session_id = ?, reviewer_session_url = ? WHERE id = ?",
        session_id, session_url, run_id,
    )


def update_reviewer_done(run_id: int, status: str, verdict: str = None) -> None:
    """Mark the reviewer phase complete and store its verdict."""
    _exec(
        "UPDATE pipeline_runs SET reviewer_status = ?, reviewer_verdict = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
        status, verdict, run_id,
    )


def update_failure(run_id: int, reason: str) -> None:
    """Mark a run as failed and store the failure reason."""
    _exec(
        "UPDATE pipeline_runs SET fixer_status = 'failed', failure_reason = ? WHERE id = ?",
        reason, run_id,
    )


def get_all_runs() -> list:
    """Return all pipeline runs as dicts, newest first."""
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM pipeline_runs ORDER BY dispatched_at DESC")
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
