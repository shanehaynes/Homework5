"""Data types shared by the Campus Customs agent team."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[str, ...] = get_args(AgentName)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
CHARTER_FILE = "_team_charter.md"


class AgentSpec(BaseModel):
    """Static definition of one agent: who it is, which MCP tools it sees, and its loop limits."""

    model_config = ConfigDict(frozen=True)

    name: AgentName
    prompt_file: str
    mcp_tools: frozenset[str]
    request_limit: int = 10  # model round-trips per run
    tool_calls_limit: int = 16  # tool executions per run

    def instructions(self) -> str:
        """Static system prompt (charter + role). Static text keeps the provider's prompt-prefix cache warm."""
        charter = (PROMPTS_DIR / CHARTER_FILE).read_text(encoding="utf-8")
        role = (PROMPTS_DIR / self.prompt_file).read_text(encoding="utf-8")
        return f"{charter}\n\n{role}\n\nYou are the **{self.name}** agent."


class AgentReport(BaseModel):
    """What every agent run returns to its caller (boss, another agent, or the dashboard)."""

    status: Literal["done", "in_progress", "blocked", "needs_human", "failed"]
    summary: str = Field(description="60 words or fewer: what happened and where things stand")
    ticket_ids: list[int] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list, description="Concrete actions taken, with ids (e.g. 'PO 3', 'approval 2')")
    needs_human: list[str] = Field(default_factory=list, description="Decisions only a human can make, with approval ids")
    follow_ups: list[str] = Field(default_factory=list, description="Open items for the team")


class DelegationResult(BaseModel):
    """Returned by the delegate tool to the delegating agent."""

    ok: bool
    to_agent: AgentName
    report: AgentReport | None = None
    error: str | None = None
    cached: bool = False


class AuditEvent(BaseModel):
    """One line of output/audit_trail.json. One event per loop step, tool call, and delegation."""

    ts: str
    root_run_id: str
    run_id: str
    agent: str
    depth: int
    parent: str | None
    ticket_id: int | None
    step: int
    event: Literal["run_start", "model_response", "tool_call", "delegation", "run_end", "run_error", "human_action"]
    data: dict[str, Any]


@dataclass
class TeamRun:
    """State shared by every agent in one delegation tree (one human-triggered job)."""

    root_run_id: str
    trigger: str
    max_delegations: int = 8
    max_depth: int = 3
    delegations: int = 0
    cache: dict[tuple, Any] = field(default_factory=dict)  # task key -> Future[DelegationResult]


@dataclass
class AgentDeps:
    """Per-agent-run dependencies passed to tools via RunContext."""

    agent: AgentName
    team: TeamRun
    run_id: str
    depth: int = 0
    chain: tuple[str, ...] = ()
    parent: str | None = None
    ticket_id: int | None = None
    step: int = 0


# ---------------------------------------------------------------------------------------------------
# API (backend/main.py)
# ---------------------------------------------------------------------------------------------------

class TicketSummary(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    status: str
    state: Literal["open", "resolved"]
    owner: str | None = None
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    created_at: str


class RunJob(BaseModel):
    """A team run started from the API. `run_id` is the audit trail's root_run_id."""

    run_id: str
    ticket_id: int
    status: Literal["running", "done", "failed"]
    started_at: str
    finished_at: str | None = None
    report: AgentReport | None = None
    error: str | None = None


class DecisionRequest(BaseModel):
    decided_by: str = Field(min_length=1, description="Name of the human clicking the button")
    note: str = ""


class CashBalance(BaseModel):
    account: str
    balance: float
    shop_date: str
