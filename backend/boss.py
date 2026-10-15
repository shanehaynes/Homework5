"""Boss: orchestrates the team, routes tickets, and decides next steps from specialists' reports."""

from backend._common import COMMON_TOOLS
from backend.models import AgentSpec

SPEC = AgentSpec(
    name="boss",
    prompt_file="boss.md",
    mcp_tools=COMMON_TOOLS | {
        "get_cash_position",
        "list_inventory",
        "list_vendors",
        "list_leases",
        "list_purchase_orders",
        "quote_order",
    },
    request_limit=14,
    tool_calls_limit=24,
)
