"""Campus Customs API for the human-oversight dashboard.

Run from backend/:  ../.venv/bin/uvicorn main:app --reload --port 8000

Shop reads and writes go through the campus-customs MCP server, the same path the agents use. The only
direct database access is /reset, which restores the original file wholesale.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `backend.*` imports work when uvicorn runs from backend/

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from backend import audit, team  # noqa: E402
from backend.tenet_bridge import router as tenet_router  # noqa: E402
from backend.models import AuditEvent, CashBalance, DecisionRequest, RunJob, TicketSummary  # noqa: E402

ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
# CAMPUS_DB_PATH (Tenet bridge) points the backend and the MCP server at a separate working copy.
WORKING_DB = ROOT / os.getenv("CAMPUS_DB_PATH", "data/campus_customs_new.db")

jobs: dict[str, RunJob] = {}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


async def _mcp(tool: str, args: dict[str, Any] | None = None) -> Any:
    return await team.mcp_toolset().direct_call_tool(tool, args or {})


def _record_human(action: str, data: dict[str, Any], ticket_id: int | None = None) -> None:
    """Human actions go in the same audit trail as agent steps."""
    audit.append(AuditEvent(
        ts=datetime.now().astimezone().isoformat(timespec="milliseconds"), root_run_id="human", run_id=uuid.uuid4().hex[:10],
        agent="human", depth=0, parent=None, ticket_id=ticket_id, step=1, event="human_action", data={"action": action, **data},
    ).model_dump())


def _running() -> list[RunJob]:
    return [j for j in jobs.values() if j.status == "running"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not WORKING_DB.exists():  # a new CAMPUS_DB_PATH starts as a copy of the original books
        shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    async with team.mcp_toolset():  # one MCP server process for the API's lifetime
        yield


app = FastAPI(title="Campus Customs Desk", lifespan=lifespan)
app.include_router(tenet_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# 1. Tickets ------------------------------------------------------------------------------------------

@app.get("/tickets", response_model=list[TicketSummary])
async def list_tickets() -> list[TicketSummary]:
    """Every ticket with its raw status, open/resolved state, and owner."""
    rows = await _mcp("list_tickets")
    return [TicketSummary(**r, state="resolved" if r["status"] == "resolved" else "open") for r in rows]


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict:
    """One ticket in full: notes, owner, recent messages, approvals, purchase orders, latest reply draft."""
    result = await _mcp("get_ticket", {"ticket_id": ticket_id, "message_limit": 20})
    if not result.get("found"):
        raise HTTPException(404, f"ticket {ticket_id} not found")
    return result


@app.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: int, body: DecisionRequest) -> dict:
    """A human marks a ticket resolved (e.g. after reviewing a parked run). `note` is required."""
    result = await _mcp("resolve_ticket", {"ticket_id": ticket_id, "resolved_by": body.decided_by, "note": body.note})
    _record_human("resolve_ticket", {"decided_by": body.decided_by, "note": body.note, "result": result}, ticket_id)
    if not result.get("ok"):
        raise HTTPException(409, result)
    return result


@app.post("/tickets/{ticket_id}/direct")
async def direct_ticket(ticket_id: int, body: DecisionRequest) -> dict:
    """A human gives the team a decision or instruction on a ticket (`note`); boss acts on it at the next run."""
    result = await _mcp("add_human_direction", {"ticket_id": ticket_id, "author": body.decided_by, "direction": body.note})
    _record_human("direct_ticket", {"decided_by": body.decided_by, "note": body.note, "result": result}, ticket_id)
    if not result.get("ok"):
        raise HTTPException(409, result)
    return result


# 2. Run the team on a ticket --------------------------------------------------------------------------

async def _run(job: RunJob) -> None:
    try:
        job.report = await team.run_ticket(job.ticket_id, root_run_id=job.run_id)
        job.status = "done"
    except Exception as e:
        job.status, job.error = "failed", f"{type(e).__name__}: {e}"
    job.finished_at = _now()


@app.post("/tickets/{ticket_id}/run", response_model=RunJob, status_code=202)
async def run_ticket(ticket_id: int) -> RunJob:
    """Start the agent team (boss first) on one ticket. Returns immediately; poll /runs/{run_id}."""
    found = await _mcp("get_ticket", {"ticket_id": ticket_id, "message_limit": 1})
    if not found.get("found"):
        raise HTTPException(404, f"ticket {ticket_id} not found")
    if any(j.ticket_id == ticket_id for j in _running()):
        raise HTTPException(409, f"ticket {ticket_id} already has a run in progress")
    job = RunJob(run_id=uuid.uuid4().hex[:10], ticket_id=ticket_id, status="running", started_at=_now())
    jobs[job.run_id] = job
    asyncio.create_task(_run(job))
    return job


@app.get("/runs", response_model=list[RunJob])
async def list_runs() -> list[RunJob]:
    """Runs started since the API process began, newest first."""
    return sorted(jobs.values(), key=lambda j: j.started_at, reverse=True)


@app.get("/runs/{run_id}", response_model=RunJob)
async def get_run(run_id: str) -> RunJob:
    if run_id not in jobs:
        raise HTTPException(404, f"run {run_id} not found")
    return jobs[run_id]


# 3. Agent activity -------------------------------------------------------------------------------------

@app.get("/activity")
async def activity(
    limit: int = Query(50, ge=1, le=500),
    ticket_id: int | None = None,
    run_id: str | None = Query(None, description="root_run_id of a run"),
) -> list[dict]:
    """Most recent audit-trail events (agent steps, tool calls, delegations, human actions), newest first."""
    if not audit.AUDIT_PATH.exists():
        return []
    events = json.loads(audit.AUDIT_PATH.read_text())
    if ticket_id is not None:
        events = [e for e in events if e.get("ticket_id") == ticket_id]
    if run_id is not None:
        events = [e for e in events if e.get("root_run_id") == run_id]
    return events[-limit:][::-1]


# 4. Human approvals --------------------------------------------------------------------------------------

@app.get("/approvals")
async def list_approvals(status: str = "pending") -> list[dict]:
    """Approval requests (payments, purchases, discounts) waiting for a human, or by any status."""
    return await _mcp("list_approvals", {"status": status})


async def _decide(approval_id: int, decision: str, body: DecisionRequest) -> dict:
    result = await _mcp("decide_approval", {"approval_id": approval_id, "decision": decision,
                                            "decided_by": body.decided_by, "note": body.note})
    _record_human(f"{decision}_approval", {"approval_id": approval_id, "decided_by": body.decided_by, "result": result})
    if not result.get("ok"):
        raise HTTPException(409, result)
    return result


@app.post("/approvals/{approval_id}/approve")
async def approve(approval_id: int, body: DecisionRequest) -> dict:
    """Human approves. A payment executes immediately (cash rechecked; refused if short); a purchase order is
    placed (vendor standing and cash rechecked); a discount is recorded."""
    return await _decide(approval_id, "approve", body)


@app.post("/approvals/{approval_id}/reject")
async def reject(approval_id: int, body: DecisionRequest) -> dict:
    """Human rejects a pending request."""
    return await _decide(approval_id, "reject", body)


# 5. Cash ----------------------------------------------------------------------------------------------------

@app.get("/cash", response_model=CashBalance)
async def cash() -> CashBalance:
    """Current checking balance from cash_accounts, with the shop date."""
    overview = await _mcp("get_shop_overview")
    checking = next((c for c in overview["cash"] if c["name"] == "checking"), None)
    if checking is None:
        raise HTTPException(404, "no checking account")
    return CashBalance(account="checking", balance=checking["balance"], shop_date=overview["today"])


# 6. Reset ---------------------------------------------------------------------------------------------------

@app.post("/reset")
async def reset() -> dict:
    """Restore the working database from the original campus_customs.db. Refused while a run is in progress.
    The audit trail is append-only and is not cleared; a reset marker is appended instead."""
    if _running():
        raise HTTPException(409, "a team run is in progress; wait for it to finish")
    src, dst = sqlite3.connect(ORIGINAL_DB), sqlite3.connect(WORKING_DB)
    try:
        src.backup(dst)  # page-level copy; safe even if another connection has the file open
    finally:
        src.close()
        dst.close()
    jobs.clear()
    overview = await _mcp("get_shop_overview")  # also recreates the coordination tables
    _record_human("reset_database", {"from": ORIGINAL_DB.name, "to": WORKING_DB.name})
    return {"ok": True, "cash": overview["cash"], "open_tickets": len(overview["open_tickets"]), "today": overview["today"]}
