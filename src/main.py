"""FastAPI app: GitHub webhook receiver, manual trigger, and dashboard host."""
import hmac
import hashlib
import os
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

from src.db import get_all_runs, init_db
from src.orchestrator import dispatch_in_background
from src.scanner import run_scan
from src.scheduler import get_schedule_status, register_schedule

load_dotenv()

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

app = FastAPI(title="Devin Autofix Pipeline")


@app.on_event("startup")
def on_startup() -> None:
    """Initialize the database when the server starts."""
    init_db()
    print("[startup] devin-autofix-pipeline ready - db initialized")


def verify_gh_signature(body: bytes, sig_header: str) -> bool:
    """Verify the GitHub HMAC-SHA256 signature on a webhook payload."""
    if WEBHOOK_SECRET == "":
        return True
    if not sig_header:
        return False
    mac = hmac.new(WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected, sig_header)


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
) -> dict:
    """Receive GitHub issue webhooks and dispatch the pipeline on the autofix label."""
    body = await request.body()
    if not verify_gh_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    if x_github_event == "issues" and payload.get("action") == "labeled":
        label_name = (payload.get("label") or {}).get("name", "")
        if label_name == "autofix":
            issue_number = payload["issue"]["number"]
            print(f"[webhook] autofix label applied to issue #{issue_number}")
            background_tasks.add_task(dispatch_in_background, issue_number, "webhook")

    return {"status": "ok"}


@app.post("/trigger/{issue_number}")
def manual_trigger(issue_number: int, background_tasks: BackgroundTasks) -> dict:
    """Manually dispatch the pipeline for a given issue number (for testing/demo)."""
    background_tasks.add_task(dispatch_in_background, issue_number, "manual")
    return {"status": "dispatched", "issue_number": issue_number}


@app.post("/scan")
def trigger_scan(background_tasks: BackgroundTasks) -> dict:
    """Kick off a vulnerability scan in the background and return immediately."""
    background_tasks.add_task(run_scan)
    return {
        "status": "scan started",
        "message": "Scanner running in background. New issues will trigger the autofix pipeline automatically.",
    }


@app.post("/schedule")
def schedule_create(cron: str = "0 9 * * 1-5") -> dict:
    """Register (or fetch) the recurring Devin schedule that runs the scanner."""
    try:
        return register_schedule(cron)
    except Exception as e:
        return {"error": str(e)}


@app.get("/schedule")
def schedule_status() -> dict:
    """Return the current Devin schedule list for this org."""
    return get_schedule_status()


@app.get("/api/runs")
def api_runs() -> JSONResponse:
    """Return all pipeline runs as JSON for the dashboard."""
    return JSONResponse(get_all_runs())


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """Serve the static dashboard HTML page."""
    try:
        with open("dashboard/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<p>Dashboard not found. Expected dashboard/index.html.</p>")
