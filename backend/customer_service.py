"""Customer Service: catalog knowledge, order answers, quotes, discount requests, reply drafts."""

from backend._common import COMMON_TOOLS
from backend.models import AgentSpec

SPEC = AgentSpec(
    name="customer_service",
    prompt_file="customer_service.md",
    mcp_tools=COMMON_TOOLS | {
        "get_catalog",
        "check_stock",
        "quote_order",
        "request_discount_approval",
        "draft_customer_reply",
    },
)
