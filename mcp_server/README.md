# Campus Customs MCP Server

## Purpose
This server is the single path from the agent team (Boss, Inventory, Accounting, Facilities, Customer Service) to the shop database. There is no second tool layer, and no agent writes SQL. Business rules live in the tools, so a confused or manipulated model can't break them:
- the desk date is "today"
- vendor lead times set ETAs
- no shipping while a vendor has an open invoice
- human-approved payments only
- nothing beyond cash on hand

## What it interacts with
- **Database:** `data/campus_customs_new.db`, the working copy, via `DB_PATH` (set in `.mcp.json`; relative paths resolve against `hw5/`). The original `data/campus_customs.db` is never touched.
- **Shop tables:** `desk`, `inventory`, `pricing`, `vendors`, `invoices`, `leases`, `cash_accounts`, `payments`, `tickets`.
- **Coordination tables** (created on startup if missing): `ticket_assignments`, `agent_messages`, `approval_requests`, `purchase_orders`, `inventory_movements`, `customer_replies`, `facility_issues`.
- **No external systems.** Nothing emails customers or contacts vendors. Replies are drafts; POs are internal records.
- **Identity:** write tools take an `agent` argument. The backend injects it from the calling agent and hides it from the model's schema.

## Tools (32)

**Shared: awareness and coordination**
| Tool | What it does |
|---|---|
| `get_shop_overview()` | One-call snapshot: shop date, cash, open tickets with owners, open invoices, rent due in 14 days, pending approvals, low stock, blocked vendors. |
| `list_tickets(status?)` | Tickets with owners (no notes). |
| `get_ticket(ticket_id, message_limit=8)` | Ticket plus owner, recent messages, approvals, POs, latest reply draft, facility issues. |
| `assign_ticket(ticket_id, owner, agent)` | Claim a ticket, or (boss) reassign it. Refuses if another agent owns it. |
| `update_ticket(ticket_id, note, agent, status?)` | Append a signed, dated note and optionally set status. Auto-claims an unowned ticket. |
| `send_message(to_agent, body, agent, ticket_id?, kind)` | Message an agent or `all`; boss is always copied. |
| `read_messages(agent, ticket_id?, unread_only, limit)` | Inbox (boss sees everything) and mark read. |
| `list_approvals(status)` | Human-approval requests (payments, discounts). |

**Inventory and purchasing**
| Tool | What it does |
|---|---|
| `check_stock(sku, size, qty=1)` | On-hand, shortfall, on order, location, cost, price. |
| `list_inventory(only_low=False)` | All rows with an out/low/ok flag (low = 3 or fewer) and units on order. |
| `get_demand_signals(days=30)` | On-hand vs on-order vs open ticket demand vs recent outflow; flags `stockout_risk` / `slow_mover`. |
| `adjust_inventory(sku, size, delta, reason, agent, ticket_id?)` | Shelf change with a reason; never below zero; logged to `inventory_movements`. |
| `list_vendors()` | Vendors with lead days, will-ship status, open invoice total, ETA. |
| `check_vendor_restock(vendor_id)` | Will this vendor ship? Blocking invoices and ETAs. |
| `create_purchase_order(vendor_id, sku, size, qty, agent, ticket_id?)` | Files an internal PO as `pending_approval` plus a human approval request. Refuses for a blocked vendor, insufficient cash, or a duplicate. |
| `list_purchase_orders(status)` | POs by status. |
| `receive_purchase_order(po_id, agent)` | On or after the ETA: adds stock and books the vendor invoice (due in 30 days). |

**Accounting**
| Tool | What it does |
|---|---|
| `get_cash_position(horizon_days=30)` | Cash vs invoices, rent, and open POs in the horizon; projected balance and shortfall. |
| `list_invoices(status)` | Invoices with vendor and overdue flag. |
| `list_payments(limit)` | Recorded (human-approved) payments. |
| `preview_payment(kind, ref_id)` | What paying would do, with no writes: balance after, sufficiency, prior payments, pending approval. |
| `request_payment_approval(kind, ref_id, reason, agent, ticket_id?)` | File a payment for human approval. Refuses for insufficient cash, a paid invoice, or a duplicate. |

**Customer service and pricing**
| Tool | What it does |
|---|---|
| `get_catalog()` | Customer-facing products, list prices, stock by size (no costs). |
| `quote_order(sku, size, qty, discount_pct=0)` | Price, total, cost, margin $/%, stock coverage. Any discount requires approval. |
| `request_discount_approval(ticket_id, sku, size, qty, discount_pct, reason, agent)` | File a discount for human approval, with its margin. |
| `draft_customer_reply(ticket_id, body, agent)` | Save a reply draft (supersedes the previous one). Never sent. |

**Facilities**
| Tool | What it does |
|---|---|
| `list_leases()` | Rent, next due, days until due, overdue, last payment. |
| `report_facility_issue(issue, severity, agent, lease_id?, ticket_id?)` | Log a maintenance, safety, or quality issue. |
| `list_facility_issues(status)` | Facility issues by status. |

**Human only (dashboard; never exposed to agents)**
| Tool | What it does |
|---|---|
| `decide_approval(approval_id, decision, decided_by, note?)` | Approve or reject. Approving a payment executes it atomically: rechecks cash, inserts into `payments`, debits `cash_accounts`, marks the invoice paid or advances the lease's `next_due`. Approving a purchase places the PO (vendor standing and cash rechecked; ETA from today). Rejects agent names as `decided_by`. |
| `resolve_ticket(ticket_id, resolved_by, note)` | A human marks a ticket resolved with a signed note. |
| `add_human_direction(ticket_id, author, direction)` | A human's decision or instruction: appended to the notes as `DIRECTION:` and sent to boss's inbox. |

`pay_bill` from Problem 3 was split into `preview_payment`, `request_payment_approval`, and `decide_approval`. Problem 4's one-time smoke-test evidence is in `output/mcp_smoke.json`.

## Run
```bash
# from hw5/, using the root requirements.txt
.venv/bin/pip install -r requirements.txt
.venv/bin/python mcp_server/server.py
```
Uses stdio transport. The agent backend starts it automatically from `.mcp.json`.
