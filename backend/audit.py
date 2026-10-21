"""Append-only audit trail at output/audit_trail.json (a JSON array; earlier entries are never rewritten)."""

import fcntl
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.models import AgentDeps, AuditEvent

_ROOT = Path(__file__).resolve().parent.parent
# CAMPUS_AUDIT_PATH (Tenet bridge) sends a test session's events to a separate, git-ignored file.
AUDIT_PATH = _ROOT / os.getenv("CAMPUS_AUDIT_PATH", "output/audit_trail.json")
CLIP = 1500  # max characters of any single logged value
_lock = threading.Lock()


def clip(value: Any, limit: int = CLIP) -> Any:
    """Keep audit entries readable: long strings and big structures are truncated, not dropped."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"... [+{len(value) - limit} chars]"
    text = json.dumps(value, default=str, ensure_ascii=False)
    return value if len(text) <= limit else text[:limit] + f"... [+{len(text) - limit} chars]"


def record(deps: AgentDeps, event: str, data: dict[str, Any]) -> None:
    """Append one audit event for the agent run described by `deps`."""
    deps.step += 1
    entry = AuditEvent(
        ts=datetime.now().astimezone().isoformat(timespec="milliseconds"),
        root_run_id=deps.team.root_run_id,
        run_id=deps.run_id,
        agent=deps.agent,
        depth=deps.depth,
        parent=deps.parent,
        ticket_id=deps.ticket_id,
        step=deps.step,
        event=event,
        data=data,
    )
    append(entry.model_dump())


def append(entry: dict) -> None:
    """Append one entry to the JSON array in place: drop the closing bracket, write the entry, re-close."""
    body = json.dumps(entry, ensure_ascii=False, indent=2, default=str)
    body = "\n".join("  " + line for line in body.splitlines()).encode()
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(AUDIT_PATH, "a+b") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                f.write(b"[\n" + body + b"\n]\n")
                return
            f.seek(max(0, size - 4096))
            tail = f.read()
            close = tail.rfind(b"]")
            if close == -1:
                raise ValueError(f"{AUDIT_PATH} does not end with ']'; refusing to modify it")
            before = tail[:close].rstrip()
            f.truncate(size - len(tail) + len(before))
            f.write((b"\n" if before.endswith(b"[") else b",\n") + body + b"\n]\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
