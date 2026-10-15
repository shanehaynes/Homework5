"""Inventory: stock truth, low-stock alerts, demand signals, purchase orders, receiving, fulfillment."""

from backend._common import COMMON_TOOLS
from backend.models import AgentSpec

SPEC = AgentSpec(
    name="inventory",
    prompt_file="inventory.md",
    mcp_tools=COMMON_TOOLS | {
        "check_stock",
        "list_inventory",
        "get_demand_signals",
        "adjust_inventory",
        "list_vendors",
        "check_vendor_restock",
        "create_purchase_order",
        "list_purchase_orders",
        "receive_purchase_order",
    },
)
