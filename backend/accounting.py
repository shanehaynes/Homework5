"""Accounting: cash position, invoices, payment approval requests, margin checks, early warnings."""

from backend._common import COMMON_TOOLS
from backend.models import AgentSpec

SPEC = AgentSpec(
    name="accounting",
    prompt_file="accounting.md",
    mcp_tools=COMMON_TOOLS | {
        "get_cash_position",
        "list_invoices",
        "list_payments",
        "preview_payment",
        "request_payment_approval",
        "check_vendor_restock",
        "list_vendors",
        "list_purchase_orders",
        "quote_order",
        "request_discount_approval",
        "list_leases",
    },
)
