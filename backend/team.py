"""Campus Customs agent team runtime: PydanticAI agents over the campus-customs MCP server, with delegation.

Every agent talks to the shop only through MCP. The backend adds two things the MCP server cannot:
  * identity: the `agent` argument on write tools is injected from the calling agent, never chosen by the model;
  * delegation: `delegate` runs another agent and returns its report (boss is copied via send_message).

CLI (from hw5/):
    .venv/bin/python -m backend.team shift
    .venv/bin/python -m backend.team ticket 101
    .venv/bin/python -m backend.team ask inventory "Which items are low?"
"""

import argparse
import asyncio
import copy
import dataclasses
import json
import os
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastmcp import Client
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import CallToolFunc, MCPToolset
from pydantic_ai.messages import TextPart, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits

from backend import accounting, boss, customer_service, facilities, inventory
from backend.audit import clip, record
from backend.models import AgentDeps, AgentName, AgentReport, AgentSpec, DelegationResult, TeamRun

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")  # course convention: the repo folder first, then one level up
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

MODEL_NAME = os.getenv("MODEL", "gpt-6-luna")
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
MCP_CONFIG_PATH = ROOT / ".mcp.json"

SPECS: dict[str, AgentSpec] = {s.name: s for s in (boss.SPEC, inventory.SPEC, accounting.SPEC, facilities.SPEC, customer_service.SPEC)}
HUMAN_ONLY_TOOLS = frozenset({"decide_approval", "resolve_ticket", "add_human_direction"})
IDENTITY_PARAM = "agent"
_identity_tools: set[str] = set()  # MCP tools whose `agent` arg the backend fills in

model_override: Model | None = None  # tests swap in a PydanticAI TestModel/FunctionModel here


# ---------------------------------------------------------------------------------------------------
# Model and MCP connection
# ---------------------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _portkey_model() -> Model:
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise RuntimeError(f"PORTKEY_API_KEY is missing from {ROOT / '.env'} (copy .env.example to .env)")
    if os.getenv("CAMPUS_FRESH_MODEL_CALLS") == "1":
        # Tenet bridge: Portkey replays identical requests from a response cache, so a repeated test would replay
        # the earlier answer. Ask for a fresh one on every call.
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=PORTKEY_BASE_URL, api_key=api_key, default_headers={"x-portkey-cache-force-refresh": "true"})
        return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(base_url=PORTKEY_BASE_URL, api_key=api_key))


def get_model() -> Model:
    return model_override or _portkey_model()


@lru_cache(maxsize=1)
def mcp_toolset() -> MCPToolset:
    """One MCP connection (from .mcp.json) shared by every agent; reference-counted, so nested runs reuse it."""
    config = json.loads(MCP_CONFIG_PATH.read_text())
    for server in config["mcpServers"].values():  # .mcp.json uses repo-relative paths; resolve them from any cwd
        if (ROOT / server["command"]).exists():
            server["command"] = str(ROOT / server["command"])
        server["args"] = [str(ROOT / a) if (ROOT / a).exists() else a for a in server.get("args", [])]
        if os.getenv("CAMPUS_DB_PATH"):  # Tenet bridge: run against a separate working copy of the books
            server.setdefault("env", {})["DB_PATH"] = os.environ["CAMPUS_DB_PATH"]
    return MCPToolset(Client(config), process_tool_call=_process_tool_call)


async def _prepare_tools(ctx: RunContext[AgentDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
    """Show each agent only its role's tools, and hide the identity argument (the backend sets it)."""
    allowed = SPECS[ctx.deps.agent].mcp_tools
    out = []
    for td in tool_defs:
        if td.name not in allowed or td.name in HUMAN_ONLY_TOOLS:
            continue
        props = td.parameters_json_schema.get("properties", {})
        if IDENTITY_PARAM in props:
            _identity_tools.add(td.name)
            schema = copy.deepcopy(td.parameters_json_schema)
            del schema["properties"][IDENTITY_PARAM]
            schema["required"] = [r for r in schema.get("required", []) if r != IDENTITY_PARAM]
            td = dataclasses.replace(td, parameters_json_schema=schema)
        out.append(td)
    return out


async def _process_tool_call(ctx: RunContext[AgentDeps], call_tool: CallToolFunc, name: str, args: dict[str, Any]) -> Any:
    """Every MCP call passes here: enforce the role allowlist, inject identity, and audit the call and result."""
    deps = ctx.deps
    if name in HUMAN_ONLY_TOOLS or name not in SPECS[deps.agent].mcp_tools:
        result: Any = {"ok": False, "error": f"{name} is not available to {deps.agent}"}
    else:
        if name in _identity_tools:
            args = {**args, IDENTITY_PARAM: deps.agent}
        try:
            result = await call_tool(name, args)
        except Exception as e:  # surface tool failures to the model and the audit trail alike
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    record(deps, "tool_call", {"tool": name, "args": args, "result": clip(result)})
    return result


async def _post_message(sender: str, to_agent: str, body: str, ticket_id: int | None, kind: str) -> None:
    """Record team communication through MCP (boss is cc'd by the server)."""
    await mcp_toolset().direct_call_tool(
        "send_message", {"to_agent": to_agent, "body": body, "agent": sender, "ticket_id": ticket_id, "kind": kind}
    )


# ---------------------------------------------------------------------------------------------------
# Delegation (available to every agent)
# ---------------------------------------------------------------------------------------------------

async def delegate(ctx: RunContext[AgentDeps], to_agent: AgentName, task: str, ticket_id: int | None = None) -> DelegationResult:
    """Hand a task to another agent and wait for its report. Boss is copied automatically.

    Make the task self-contained: ticket id, SKUs, amounts, ids, and exactly what you need back.
    """
    deps, team = ctx.deps, ctx.deps.team
    ticket_id = ticket_id or deps.ticket_id

    def refuse(reason: str) -> DelegationResult:
        record(deps, "delegation", {"to": to_agent, "task": clip(task), "ok": False, "error": reason})
        return DelegationResult(ok=False, to_agent=to_agent, error=reason)

    if to_agent == deps.agent:
        return refuse("cannot delegate to yourself")
    if to_agent in deps.chain:
        return refuse(f"{to_agent} is already in this chain ({' -> '.join(deps.chain)}); return your findings to your caller instead")
    if deps.depth + 1 > team.max_depth:
        return refuse(f"max delegation depth {team.max_depth} reached; report back to your caller")
    key = (to_agent, ticket_id, " ".join(task.lower().split()))
    if key in team.cache:  # identical task already done or in flight in this job: share it, don't redo it
        record(deps, "delegation", {"to": to_agent, "task": clip(task), "ok": True, "cached": True})
        return (await team.cache[key]).model_copy(update={"cached": True})
    if team.delegations >= team.max_delegations:
        return refuse(f"delegation budget ({team.max_delegations}) for this job is used up; report what remains")

    team.delegations += 1
    pending: asyncio.Future[DelegationResult] = asyncio.get_running_loop().create_future()
    team.cache[key] = pending
    child = AgentDeps(
        agent=to_agent, team=team, run_id=uuid.uuid4().hex[:10], depth=deps.depth + 1,
        chain=(*deps.chain, to_agent), parent=deps.agent, ticket_id=ticket_id,
    )
    record(deps, "delegation", {"to": to_agent, "task": clip(task), "child_run_id": child.run_id, "n": team.delegations})
    await _post_message(deps.agent, to_agent, task, ticket_id, "delegation")

    prompt = f"Task from {deps.agent} (chain: {' -> '.join(child.chain)}):\n{task}"
    if ticket_id:
        prompt += f"\nTicket: {ticket_id}"
    try:
        report = await run_agent(child, prompt)
    except Exception as e:
        result = DelegationResult(ok=False, to_agent=to_agent, error=f"{to_agent} failed: {type(e).__name__}: {e}")
    else:
        result = DelegationResult(ok=True, to_agent=to_agent, report=report)
        await _post_message(to_agent, deps.agent, f"[{report.status}] {report.summary}", ticket_id, "delegation_result")
    pending.set_result(result)
    return result


# ---------------------------------------------------------------------------------------------------
# Agents and the agent loop
# ---------------------------------------------------------------------------------------------------

@lru_cache(maxsize=None)
def get_agent(name: str) -> Agent[AgentDeps, AgentReport]:
    spec = SPECS[name]
    return Agent(
        name=name,
        deps_type=AgentDeps,
        output_type=AgentReport,
        instructions=spec.instructions(),
        toolsets=[mcp_toolset().prepared(_prepare_tools)],
        tools=[delegate],
        retries=2,
    )


def _summarize_response(response) -> dict[str, Any]:
    usage = response.usage
    return {
        "model": response.model_name,
        "finish_reason": response.finish_reason,
        "text": clip(" ".join(p.content for p in response.parts if isinstance(p, TextPart)).strip()) or None,
        "tool_calls": [{"tool": p.tool_name, "args": clip(p.args_as_dict())} for p in response.parts if isinstance(p, ToolCallPart)],
        "usage": {"input": usage.input_tokens, "output": usage.output_tokens, "cache_read": usage.cache_read_tokens},
    }


async def run_agent(deps: AgentDeps, prompt: str) -> AgentReport:
    """Run one agent's loop (model -> tools -> model ... -> report), auditing every step."""
    spec = SPECS[deps.agent]
    record(deps, "run_start", {"prompt": clip(prompt), "chain": list(deps.chain), "trigger": deps.team.trigger})
    limits = UsageLimits(request_limit=spec.request_limit, tool_calls_limit=spec.tool_calls_limit)
    try:
        async with get_agent(deps.agent).iter(prompt, deps=deps, model=get_model(), usage_limits=limits) as run:
            async for node in run:
                if Agent.is_call_tools_node(node):
                    record(deps, "model_response", _summarize_response(node.model_response))
            report = run.result.output
            usage = run.usage
    except Exception as e:
        record(deps, "run_error", {"error": f"{type(e).__name__}: {clip(str(e), 500)}"})
        raise
    record(deps, "run_end", {
        "report": report.model_dump(),
        "usage": {"requests": usage.requests, "tool_calls": usage.tool_calls, "input": usage.input_tokens,
                  "output": usage.output_tokens, "cache_read": usage.cache_read_tokens},
    })
    return report


# ---------------------------------------------------------------------------------------------------
# Entry points (CLI now; FastAPI later)
# ---------------------------------------------------------------------------------------------------

@asynccontextmanager
async def team_session() -> AsyncIterator[None]:
    """Hold one MCP server process open for a whole job."""
    async with mcp_toolset():
        yield


def _root_deps(agent: AgentName, trigger: str, ticket_id: int | None = None, root_run_id: str | None = None) -> AgentDeps:
    team = TeamRun(root_run_id=root_run_id or uuid.uuid4().hex[:10], trigger=trigger)
    return AgentDeps(agent=agent, team=team, run_id=team.root_run_id, chain=(agent,), ticket_id=ticket_id)


async def run_ticket(ticket_id: int, root_run_id: str | None = None) -> AgentReport:
    """Boss takes one ticket end to end. `root_run_id` lets callers find this run in the audit trail."""
    deps = _root_deps("boss", f"ticket {ticket_id}", ticket_id, root_run_id)
    async with team_session():
        return await run_agent(deps, f"Handle ticket {ticket_id}. Route it, delegate, decide, and leave it correctly parked or resolved.")


async def run_shift() -> AgentReport:
    """Boss works every open ticket and runs the shift review (demand signals, cash position)."""
    deps = _root_deps("boss", "shift")
    async with team_session():
        return await run_agent(deps, "Start of shift. Work every open ticket, then run the shift review. Report decisions a human must make.")


async def ask_agent(agent: AgentName, message: str, ticket_id: int | None = None) -> AgentReport:
    """A human asks one agent directly. Boss is kept in the loop with an update message."""
    deps = _root_deps(agent, f"ask {agent}", ticket_id)
    async with team_session():
        report = await run_agent(deps, f"Request from a human operator:\n{message}" + (f"\nTicket: {ticket_id}" if ticket_id else ""))
        if agent != "boss":
            await _post_message(agent, "boss", f"Handled a direct human request. [{report.status}] {report.summary}", ticket_id, "update")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Campus Customs agent team.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("shift")
    t = sub.add_parser("ticket")
    t.add_argument("ticket_id", type=int)
    a = sub.add_parser("ask")
    a.add_argument("agent", choices=list(SPECS))
    a.add_argument("message")
    a.add_argument("--ticket", type=int)
    args = parser.parse_args()

    if args.cmd == "shift":
        report = asyncio.run(run_shift())
    elif args.cmd == "ticket":
        report = asyncio.run(run_ticket(args.ticket_id))
    else:
        report = asyncio.run(ask_agent(args.agent, args.message, args.ticket))
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
