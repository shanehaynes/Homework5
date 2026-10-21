"""Tenet bridge: lets Tenet (github.com/shanehaynes/tenet) test one agent of this team over HTTP.

GET /tenet/ask
-> 200 {"name", "agents", "context"}: what the agent's world holds after a reset (shop date, cash, open tickets,
   invoices, catalog, vendors), so Tenet can write test requests about records that exist

POST /tenet/ask
  {"agent": "customer_service" | "accounting" | "inventory" | "facilities" | "boss",
   "message": "<an operator request>", "conversation_id": "<Tenet scenario id>", "reset": true, "ticket_id": null}
-> 200 {"reply", "report", "actions": [{"name", "arguments", "result"}], "usage": {...}, "meta": {"root_run_id", "ms"}}
-> 409 {"error": "busy"} while a team run or another bridge request is in progress
-> 502 {"error", "actions", "usage", "meta"} when the agent ended without a report (a usage limit, a model error)
-> 504 {"error", "actions", "usage", "meta"} when the agent run exceeded TENET_AGENT_TIMEOUT_S (default 100 s;
   a hung model call would otherwise hold the books for minutes)

Each request (with reset) starts from the original books, runs the agent exactly as the dashboard's
"ask an agent" does, and returns the agent's report plus every tool call it made, read back from the audit
trail. Run the backend for Tenet against separate, git-ignored copies so the HW5 evidence stays untouched:

    cd backend && CAMPUS_DB_PATH=data/tenet_working.db CAMPUS_AUDIT_PATH=output/tenet_audit_trail.json \
        ../.venv/bin/uvicorn main:app --port 8000

The key is read from .env, or from ../.env when the repo has none (team.py).
"""

import asyncio
import json
import os
import sqlite3
import time
import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import audit, team
from backend.models import AgentName, AuditEvent
from typing import get_args

router = APIRouter(prefix="/tenet", tags=["tenet"])
AGENT_TIMEOUT_S = float(os.getenv("TENET_AGENT_TIMEOUT_S", "100"))
_lock = asyncio.Lock()


class AskRequest(BaseModel):
    agent: AgentName
    message: str = Field(min_length=1, max_length=6000)
    conversation_id: str | None = None
    reset: bool = True
    ticket_id: int | None = None


def _reset_books() -> None:
    from backend.main import ORIGINAL_DB, WORKING_DB  # imported here: main imports this module

    src, dst = sqlite3.connect(ORIGINAL_DB), sqlite3.connect(WORKING_DB)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def _trace(root_run_id: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The tool calls and token usage of one request (its agent and any it delegated to), from the audit trail.
    Usage is summed per model response, so a run that ended in an error still reports what it spent."""
    events = json.loads(audit.AUDIT_PATH.read_text()) if audit.AUDIT_PATH.exists() else []
    events = [e for e in events if e.get("root_run_id") == root_run_id]
    actions = [
        {"name": e["data"].get("tool"), "arguments": e["data"].get("args"), "result": e["data"].get("result")}
        for e in events
        if e.get("event") == "tool_call"
    ]
    usage = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "requests": 0}
    for e in events:
        if e.get("event") == "model_response":
            u = e["data"].get("usage") or {}
            usage["input_tokens"] += u.get("input") or 0
            usage["output_tokens"] += u.get("output") or 0
            usage["cached_tokens"] += u.get("cache_read") or 0
            usage["requests"] += 1
    return actions, usage


def _reply_text(report: Any) -> str:
    lines = [report.summary]
    if report.actions:
        lines.append("Actions: " + "; ".join(report.actions))
    if report.needs_human:
        lines.append("Needs human: " + "; ".join(report.needs_human))
    return "\n".join(lines)


def _compact(rows: Any) -> str:
    return json.dumps(rows, separators=(",", ":"), default=str)


@router.get("/ask")
async def describe() -> JSONResponse:
    """The original books as the agents see them; each POST starts from this state (reset: true)."""
    from backend.main import _running

    if _lock.locked() or _running():
        return JSONResponse({"error": "busy"}, status_code=409)
    async with _lock:
        _reset_books()
        call = team.mcp_toolset().direct_call_tool
        overview = await call("get_shop_overview", {})
        tickets = await call("list_tickets", {})
        catalog = await call("get_catalog", {})
        vendors = await call("list_vendors", {})
        invoices = await call("list_invoices", {"status": "open"})
    vendor_rows = [{k: v.get(k) for k in ("id", "name", "specialty", "lead_days", "will_ship", "open_invoice_total")} for v in vendors]
    context = "\n".join([
        f"Shop date: {overview['today']}. Cash: {_compact(overview['cash'])}.",
        f"Open tickets: {_compact(tickets)}",
        f"Open invoices: {_compact(invoices)}",
        f"Rent due within 14 days: {_compact(overview['rent_due_14d'])}",
        f"Pending approvals: {_compact(overview['pending_approvals'])}",
        f"Catalog (list prices; qty on hand per size): {_compact(catalog)}",
        f"Vendors: {_compact(vendor_rows)}",
    ])
    return JSONResponse({"name": "Campus Customs", "agents": list(get_args(AgentName)), "context": context})


@router.post("/ask")
async def ask(body: AskRequest) -> JSONResponse:
    from backend.main import _running  # imported here: main imports this module

    if _lock.locked() or _running():
        return JSONResponse({"error": "busy"}, status_code=409)
    async with _lock:
        if body.reset:
            _reset_books()
            await team.mcp_toolset().direct_call_tool("get_shop_overview", {})  # recreates coordination tables
        root_run_id = uuid.uuid4().hex[:10]
        deps = team._root_deps(body.agent, f"tenet {body.conversation_id or ''}".strip(), body.ticket_id, root_run_id)
        prompt = f"Request from a human operator:\n{body.message}" + (f"\nTicket: {body.ticket_id}" if body.ticket_id else "")
        started = time.monotonic()
        try:
            report = await asyncio.wait_for(team.run_agent(deps, prompt), timeout=AGENT_TIMEOUT_S)
        except TimeoutError:
            actions, usage = _trace(root_run_id)
            return JSONResponse(
                {"error": f"agent run exceeded {AGENT_TIMEOUT_S:.0f} s", "actions": actions, "usage": usage, "meta": {"root_run_id": root_run_id}},
                status_code=504,
            )
        except Exception as e:  # the agent did not produce a report (usage limit, model error): not a pass
            actions, usage = _trace(root_run_id)
            return JSONResponse(
                {"error": f"{type(e).__name__}: {e}", "actions": actions, "usage": usage, "meta": {"root_run_id": root_run_id}},
                status_code=502,
            )
        ms = int((time.monotonic() - started) * 1000)
        actions, usage = _trace(root_run_id)
        audit.append(
            AuditEvent(
                ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"), root_run_id=root_run_id, run_id=root_run_id, agent="tenet", depth=0,
                parent=None, ticket_id=body.ticket_id, step=0, event="human_action",
                data={"action": "tenet_ask", "conversation_id": body.conversation_id, "agent": body.agent},
            ).model_dump()
        )
        return JSONResponse(
            {
                "reply": _reply_text(report),
                "report": report.model_dump(),
                "actions": actions,
                "usage": usage,
                "meta": {"root_run_id": root_run_id, "ms": ms, "agent": body.agent},
            }
        )
