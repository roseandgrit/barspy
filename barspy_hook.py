#!/usr/bin/env python3
"""Bar Spy hook — updates session state from Claude Code hooks.

Called from ~/.claude/settings.json hooks with event type as argv[1].
Reads hook JSON from stdin, writes to ~/.barspy/sessions.json.

Status is set directly by the hook — no timestamp-based guessing.
"""

import json
import os
import sys
import fcntl
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_FILE = Path.home() / ".barspy" / "sessions.json"
ET = ZoneInfo("America/New_York")

# Map hook events to session status
EVENT_TO_STATUS = {
    "session-start": "idle",
    "prompt-submit": "working",
    "tool-start": "working",
    "tool-complete": "working",
    "stop": "idle",        # Claude finished responding, waiting for user
}


def read_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {"sessions": {}}


def write_state(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(data, f, indent=2)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def get_project_name(cwd):
    if not cwd:
        return "Unknown"
    return Path(cwd).name


def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    event = sys.argv[1]

    hook_input = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            hook_input = json.loads(raw)
    except (json.JSONDecodeError, OSError):
        pass

    session_id = hook_input.get("session_id") or str(os.getppid())
    pid = os.getppid()
    cwd = hook_input.get("cwd", os.getcwd())

    state = read_state()
    sessions = state.get("sessions", {})

    if event == "session-end":
        sessions.pop(session_id, None)
    else:
        if session_id not in sessions:
            now = datetime.now(ET).strftime("%-I:%M %p")
            sessions[session_id] = {
                "agent_type": "claude",
                "pid": pid,
                "project": get_project_name(cwd),
                "cwd": cwd,
                "started": now,
            }

        new_status = EVENT_TO_STATUS.get(event)
        if new_status:
            sessions[session_id]["status"] = new_status
            sessions[session_id]["last_active"] = time.time()
            sessions[session_id]["last_event"] = event

    state["sessions"] = sessions
    write_state(state)


if __name__ == "__main__":
    main()
