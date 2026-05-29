"""Client for the Devin v1 REST API."""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

DEVIN_API_KEY = os.getenv("DEVIN_API_KEY", "")
BASE_URL = "https://api.devin.ai/v1"


def _headers() -> dict:
    """Build the standard auth headers for Devin API requests."""
    return {
        "Authorization": f"Bearer {DEVIN_API_KEY}",
        "Content-Type": "application/json",
    }


def create_session(prompt: str, title: str = None, tags: list = None) -> dict:
    """Create a new Devin session and return the response containing session_id and url."""
    payload = {"prompt": prompt}
    if title is not None:
        payload["title"] = title
    if tags is not None:
        payload["tags"] = tags
    resp = requests.post(f"{BASE_URL}/sessions", json=payload, headers=_headers())
    resp.raise_for_status()
    return resp.json()


def get_session(session_id: str) -> dict:
    """Fetch the current state of a Devin session by id."""
    resp = requests.get(f"{BASE_URL}/sessions/{session_id}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def send_message(session_id: str, message: str) -> dict:
    """Send a follow-up message into an existing Devin session."""
    resp = requests.post(
        f"{BASE_URL}/sessions/{session_id}/message",
        json={"message": message},
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()


def poll_until_done(session_id: str, timeout: int = 2400, interval: int = 30) -> dict:
    """Poll a session until it reaches a terminal state or the timeout elapses.

    Only the explicit terminal states ``finished``, ``blocked`` and ``expired``
    end the loop. A ``None`` status is treated as "still initializing" because
    the Devin API can return that briefly on a freshly created session. An
    initial 15s delay gives the session time to come up before the first poll.
    """
    terminal_states = {"finished", "blocked", "expired"}
    start = time.time()
    last = {}
    time.sleep(15)
    while True:
        last = get_session(session_id)
        status = last.get("status_enum")
        print(f"  [devin] session={session_id} status={status}")
        if status in terminal_states:
            return last
        if time.time() - start > timeout:
            last["timed_out"] = True
            return last
        time.sleep(interval)
