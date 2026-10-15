"""Facilities: lease and rent obligations, shop standards, maintenance and safety issues."""

from backend._common import COMMON_TOOLS
from backend.models import AgentSpec

SPEC = AgentSpec(
    name="facilities",
    prompt_file="facilities.md",
    mcp_tools=COMMON_TOOLS | {
        "list_leases",
        "preview_payment",
        "list_payments",
        "report_facility_issue",
        "list_facility_issues",
        "get_cash_position",
    },
)
