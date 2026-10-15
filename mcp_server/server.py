"""Campus Customs MCP server: the only path from the agent team to the shop database.

Tools that write take an `agent` argument. The backend injects it from the calling agent's identity
(the model never sets it), so every write is attributable. `decide_approval` is human-only: the backend
never exposes it to agents; only the dashboard calls it.
"""

import os
import sqlite3
from calendar import monthrange
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Literal

from fastmcp import FastMCP

HW5_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", HW5_DIR / "data" / "campus_customs_new.db"))
if not DB_PATH.is_absolute():
    DB_PATH = HW5_DIR / DB_PATH

AGENTS = ("boss", "inventory", "accounting", "facilities", "customer_service")
AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
TicketStatus = Literal["open", "in_progress", "waiting_on_human", "waiting_on_vendor", "resolved", "escalated"]
LOW_STOCK = 3  # on-hand at or below this is "low"

mcp = FastMCP("campus-customs")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket_assignments (
    ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id),
    owner TEXT NOT NULL,
    assigned_by TEXT NOT NULL,
    assigned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    ticket_id INTEGER,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    read_by_recipient INTEGER NOT NULL DEFAULT 0,
    read_by_boss INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS approval_requests (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    ticket_id INTEGER,
    ref_kind TEXT,
    ref_id INTEGER,
    amount REAL,
    details TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT,
    payment_id INTEGER
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    qty INTEGER NOT NULL,
    est_cost REAL NOT NULL,
    ordered_on TEXT NOT NULL,
    eta TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'placed',
    ticket_id INTEGER,
    created_by TEXT NOT NULL,
    invoice_id INTEGER
);
CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    ticket_id INTEGER,
    agent TEXT NOT NULL,
    shop_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_replies (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    drafted_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facility_issues (
    id INTEGER PRIMARY KEY,
    lease_id INTEGER REFERENCES leases(id),
    ticket_id INTEGER,
    issue TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    reported_by TEXT NOT NULL,
    reported_on TEXT NOT NULL
);
"""


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)  # idempotent; keeps coordination tables present after a database reset
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today(conn: sqlite3.Connection) -> date:
    return date.fromisoformat(conn.execute("SELECT date_today FROM desk").fetchone()["date_today"])


def _add_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    return [{k: v for k, v in dict(r).items() if v is not None} for r in cur]


def _cash(conn: sqlite3.Connection, account: str = "checking") -> float | None:
    row = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()
    return None if row is None else row["balance"]


def _open_invoices(conn: sqlite3.Connection, vendor_id: int | None = None) -> list[sqlite3.Row]:
    sql, args = "SELECT * FROM invoices WHERE status = 'open'", ()
    if vendor_id is not None:
        sql, args = sql + " AND vendor_id = ?", (vendor_id,)
    return conn.execute(sql + " ORDER BY due_date", args).fetchall()


def _owner(conn: sqlite3.Connection, ticket_id: int) -> str | None:
    row = conn.execute("SELECT owner FROM ticket_assignments WHERE ticket_id = ?", (ticket_id,)).fetchone()
    return None if row is None else row["owner"]


def _append_note(conn: sqlite3.Connection, ticket_id: int, agent: str, note: str) -> None:
    line = f"[{_today(conn).isoformat()} {agent}] {note.strip()}"
    conn.execute(
        "UPDATE tickets SET notes = CASE WHEN notes IS NULL OR notes = '' THEN ? ELSE notes || char(10) || ? END WHERE id = ?",
        (line, line, ticket_id),
    )


def _bill(conn: sqlite3.Connection, kind: str, ref_id: int) -> tuple[dict | None, str | None]:
    """Normalize an invoice or lease into {amount, due_date, payee, ...} or return an error."""
    if kind == "invoice":
        row = conn.execute(
            "SELECT i.*, v.name AS vendor FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?", (ref_id,)
        ).fetchone()
        if row is None:
            return None, f"invoice {ref_id} not found"
        if row["status"] != "open":
            return None, f"invoice {ref_id} is already {row['status']}"
        return {"amount": row["amount"], "due_date": row["due_date"], "payee": row["vendor"], "description": row["description"]}, None
    if kind == "lease":
        row = conn.execute("SELECT * FROM leases WHERE id = ?", (ref_id,)).fetchone()
        if row is None:
            return None, f"lease {ref_id} not found"
        return {"amount": row["monthly_rent"], "due_date": row["next_due"], "payee": row["landlord"], "description": f"Rent: {row['space_name']}"}, None
    return None, "kind must be 'invoice' or 'lease'"


# ---------------------------------------------------------------------------------------------------
# Shared: situational awareness and coordination
# ---------------------------------------------------------------------------------------------------

@mcp.tool
def get_shop_overview() -> dict:
    """One-call snapshot: shop date, cash, open tickets with owners, open invoices, rent due within 14 days,
    pending approvals, low/out-of-stock items, and vendors blocked from shipping. Call this first."""
    with _db() as conn:
        today = _today(conn)
        tickets = _rows(conn.execute(
            "SELECT t.id, t.type, t.requester, t.subject, t.status, a.owner FROM tickets t "
            "LEFT JOIN ticket_assignments a ON a.ticket_id = t.id WHERE t.status != 'resolved' ORDER BY t.id"
        ))
        invoices = [
            {"id": r["id"], "vendor_id": r["vendor_id"], "amount": r["amount"], "due_date": r["due_date"],
             "overdue": date.fromisoformat(r["due_date"]) < today}
            for r in _open_invoices(conn)
        ]
        rent = [
            {"lease_id": r["id"], "landlord": r["landlord"], "amount": r["monthly_rent"], "next_due": r["next_due"],
             "days_until_due": (date.fromisoformat(r["next_due"]) - today).days}
            for r in conn.execute("SELECT * FROM leases")
            if (date.fromisoformat(r["next_due"]) - today).days <= 14
        ]
        approvals = _rows(conn.execute(
            "SELECT id, kind, ticket_id, amount, requested_by FROM approval_requests WHERE status = 'pending'"
        ))
        low = _rows(conn.execute(
            "SELECT sku, size, qty FROM inventory WHERE qty <= ? ORDER BY qty, sku", (LOW_STOCK,)
        ))
        blocked = sorted({r["vendor_id"] for r in _open_invoices(conn)})
        return {
            "today": today.isoformat(),
            "desk_notes": conn.execute("SELECT notes FROM desk").fetchone()["notes"] or "",
            "cash": _rows(conn.execute("SELECT name, balance FROM cash_accounts")),
            "open_tickets": tickets,
            "open_invoices": invoices,
            "rent_due_14d": rent,
            "pending_approvals": approvals,
            "low_stock": low,
            "vendors_blocked": blocked,
        }


@mcp.tool
def list_tickets(status: TicketStatus | None = None) -> list[dict]:
    """List tickets (optionally by status) with their current owner. Notes are omitted; use get_ticket."""
    with _db() as conn:
        sql = ("SELECT t.id, t.type, t.requester, t.subject, t.sku, t.size, t.qty, t.lease_id, t.invoice_id, t.status, "
               "t.created_at, a.owner FROM tickets t LEFT JOIN ticket_assignments a ON a.ticket_id = t.id")
        args: tuple = ()
        if status:
            sql, args = sql + " WHERE t.status = ?", (status,)
        return _rows(conn.execute(sql + " ORDER BY t.id", args))


@mcp.tool
def get_ticket(ticket_id: int, message_limit: int = 8) -> dict:
    """Full context for one ticket: the ticket, owner, recent agent messages, approvals, purchase orders,
    customer reply drafts, and facility issues tied to it. Check this before acting to avoid duplicate work."""
    with _db() as conn:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"found": False, "ticket_id": ticket_id}
        msgs = _rows(conn.execute(
            "SELECT id, from_agent, to_agent, kind, body FROM agent_messages WHERE ticket_id = ? ORDER BY id DESC LIMIT ?",
            (ticket_id, message_limit),
        ))
        return {
            "found": True,
            "ticket": {k: v for k, v in dict(t).items() if v is not None},
            "owner": _owner(conn, ticket_id),
            "recent_messages": msgs[::-1],
            "approvals": _rows(conn.execute(
                "SELECT id, kind, amount, status, requested_by, decided_by, decision_note FROM approval_requests WHERE ticket_id = ?",
                (ticket_id,))),
            "purchase_orders": _rows(conn.execute(
                "SELECT id, vendor_id, sku, size, qty, est_cost, eta, status FROM purchase_orders WHERE ticket_id = ?",
                (ticket_id,))),
            "reply_drafts": _rows(conn.execute(
                "SELECT id, status, drafted_by, body FROM customer_replies WHERE ticket_id = ? ORDER BY id DESC LIMIT 1",
                (ticket_id,))),
            "facility_issues": _rows(conn.execute(
                "SELECT id, issue, severity, status FROM facility_issues WHERE ticket_id = ?", (ticket_id,))),
        }


@mcp.tool
def assign_ticket(ticket_id: int, owner: AgentName, agent: AgentName) -> dict:
    """Claim a ticket (owner = yourself) or, if you are boss, assign/reassign it to any agent.
    Refuses if another agent already owns it, which is how duplicate work is prevented."""
    with _db() as conn:
        if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"ok": False, "error": f"ticket {ticket_id} not found"}
        current = _owner(conn, ticket_id)
        if agent != "boss" and owner != agent:
            return {"ok": False, "error": "only boss can assign a ticket to someone else", "owner": current}
        if current and current != owner and agent != "boss":
            return {"ok": False, "error": f"ticket {ticket_id} is owned by {current}; ask boss to reassign", "owner": current}
        conn.execute(
            "INSERT INTO ticket_assignments (ticket_id, owner, assigned_by, assigned_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ticket_id) DO UPDATE SET owner = excluded.owner, assigned_by = excluded.assigned_by, "
            "assigned_at = excluded.assigned_at",
            (ticket_id, owner, agent, _now()),
        )
        if current != owner:
            _append_note(conn, ticket_id, agent, f"assigned to {owner}" + (f" (was {current})" if current else ""))
        return {"ok": True, "ticket_id": ticket_id, "owner": owner, "previous_owner": current}


@mcp.tool
def update_ticket(ticket_id: int, note: str, agent: AgentName, status: TicketStatus | None = None) -> dict:
    """Append a dated, signed note to a ticket and optionally change its status. Notes are append-only.
    Any agent may add a note; only the owner or boss may change status. An unowned ticket is claimed by the caller."""
    if not note.strip():
        return {"ok": False, "error": "note is required"}
    with _db() as conn:
        if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"ok": False, "error": f"ticket {ticket_id} not found"}
        owner = _owner(conn, ticket_id)
        if status and owner and owner != agent and agent != "boss":
            return {"ok": False, "error": f"ticket {ticket_id} is owned by {owner}; only they or boss can change status"}
        if owner is None:
            conn.execute(
                "INSERT INTO ticket_assignments (ticket_id, owner, assigned_by, assigned_at) VALUES (?, ?, ?, ?)",
                (ticket_id, agent, agent, _now()),
            )
            owner = agent
        _append_note(conn, ticket_id, agent, note)
        if status:
            conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        new_status = conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()["status"]
        return {"ok": True, "ticket_id": ticket_id, "status": new_status, "owner": owner}


@mcp.tool
def send_message(to_agent: Literal["boss", "inventory", "accounting", "facilities", "customer_service", "all"],
                 body: str, agent: AgentName, ticket_id: int | None = None,
                 kind: Literal["message", "alert", "update", "question", "delegation", "delegation_result"] = "message") -> dict:
    """Send a message to another agent (or 'all'). Boss is copied on every message automatically.
    Use for FYIs, alerts, and questions; use delegate (backend) when you need the other agent to act now."""
    if not body.strip():
        return {"ok": False, "error": "body is required"}
    delivered = kind in ("delegation", "delegation_result")  # the recipient already got it inline
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO agent_messages (created_at, ticket_id, from_agent, to_agent, kind, body, read_by_recipient, read_by_boss) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), ticket_id, agent, to_agent, kind, body.strip(), int(delivered), int(agent == "boss" or (delivered and to_agent == "boss"))),
        )
        return {"ok": True, "message_id": cur.lastrowid, "cc": "boss"}


@mcp.tool
def read_messages(agent: AgentName, ticket_id: int | None = None, unread_only: bool = True, limit: int = 10) -> list[dict]:
    """Read your inbox (messages to you or 'all'; boss also sees every message as cc) and mark them read."""
    with _db() as conn:
        if agent == "boss":
            where, args = "1=1", []
            if unread_only:
                where += " AND read_by_boss = 0"
        else:
            where, args = "(to_agent = ? OR to_agent = 'all') AND from_agent != ?", [agent, agent]
            if unread_only:
                where += " AND read_by_recipient = 0"
        if ticket_id is not None:
            where += " AND ticket_id = ?"
            args.append(ticket_id)
        rows = conn.execute(
            f"SELECT id, created_at, ticket_id, from_agent, to_agent, kind, body FROM agent_messages WHERE {where} "
            "ORDER BY id DESC LIMIT ?", (*args, limit),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            marks = ",".join("?" * len(ids))
            if agent == "boss":
                conn.execute(f"UPDATE agent_messages SET read_by_boss = 1 WHERE id IN ({marks})", ids)
                conn.execute(f"UPDATE agent_messages SET read_by_recipient = 1 WHERE id IN ({marks}) AND to_agent = 'boss'", ids)
            else:
                conn.execute(f"UPDATE agent_messages SET read_by_recipient = 1 WHERE id IN ({marks})", ids)
        return [{k: v for k, v in dict(r).items() if v is not None} for r in rows[::-1]]


@mcp.tool
def list_approvals(status: Literal["pending", "approved", "rejected", "executed", "refused", "all"] = "pending") -> list[dict]:
    """List human-approval requests (payments and discounts) by status."""
    with _db() as conn:
        sql, args = "SELECT * FROM approval_requests", ()
        if status != "all":
            sql, args = sql + " WHERE status = ?", (status,)
        return _rows(conn.execute(sql + " ORDER BY id", args))


# ---------------------------------------------------------------------------------------------------
# Inventory and purchasing
# ---------------------------------------------------------------------------------------------------

@mcp.tool
def check_stock(sku: str, size: str, qty: int = 1) -> dict:
    """Can this SKU/size fill `qty` units now? Returns on-hand, shortfall, location, unit cost, list price,
    and units already on order."""
    with _db() as conn:
        item = conn.execute(
            "SELECT i.sku, i.name, i.size, i.qty, i.location, p.unit_cost, p.list_price "
            "FROM inventory i LEFT JOIN pricing p ON p.sku = i.sku WHERE i.sku = ? AND i.size = ?",
            (sku, size),
        ).fetchone()
        if item is None:
            sizes = [r["size"] for r in conn.execute("SELECT size FROM inventory WHERE sku = ?", (sku,))]
            return {"found": False, "sku": sku, "size": size, "sizes_carried": sizes}
        on_order = conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS q FROM purchase_orders WHERE sku = ? AND size = ? AND status IN ('pending_approval', 'placed')",
            (sku, size),
        ).fetchone()["q"]
    on_hand = item["qty"]
    return {
        "found": True, "sku": item["sku"], "name": item["name"], "size": item["size"], "location": item["location"],
        "requested": qty, "on_hand": on_hand, "can_fill": on_hand >= qty, "shortfall": max(qty - on_hand, 0),
        "on_order": on_order, "unit_cost": item["unit_cost"], "list_price": item["list_price"],
    }


@mcp.tool
def list_inventory(only_low: bool = False) -> list[dict]:
    """All SKU/size rows with on-hand, units on order, cost, price, and a stock flag (out/low/ok; low = <= 3)."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT i.sku, i.name, i.size, i.qty, i.location, p.unit_cost, p.list_price, "
            "(SELECT COALESCE(SUM(qty), 0) FROM purchase_orders po WHERE po.sku = i.sku AND po.size = i.size "
            " AND po.status IN ('pending_approval', 'placed')) AS on_order "
            "FROM inventory i LEFT JOIN pricing p ON p.sku = i.sku ORDER BY i.sku, i.size"
        ).fetchall()
    out = []
    for r in rows:
        flag = "out" if r["qty"] == 0 else "low" if r["qty"] <= LOW_STOCK else "ok"
        if only_low and flag == "ok":
            continue
        out.append({**dict(r), "flag": flag})
    return out


@mcp.tool
def get_demand_signals(days: int = 30) -> list[dict]:
    """Per SKU/size: on-hand, units on order, open ticket demand, and units moved out in the last `days`
    shop days. Flags 'stockout_risk' (demand exceeds on-hand + on order) and 'slow_mover' (stock but no
    movement or demand). History is only as deep as recorded movements and tickets."""
    with _db() as conn:
        today = _today(conn)
        since = (today - timedelta(days=days)).isoformat()
        rows = conn.execute(
            "SELECT i.sku, i.size, i.qty AS on_hand, "
            "(SELECT COALESCE(SUM(qty),0) FROM purchase_orders po WHERE po.sku=i.sku AND po.size=i.size AND po.status IN ('pending_approval', 'placed')) AS on_order, "
            "(SELECT COALESCE(SUM(qty),0) FROM tickets t WHERE t.sku=i.sku AND t.size=i.size AND t.status!='resolved') AS open_demand, "
            "(SELECT COALESCE(-SUM(delta),0) FROM inventory_movements m WHERE m.sku=i.sku AND m.size=i.size AND m.delta<0 AND m.shop_date>=?) AS units_out "
            "FROM inventory i ORDER BY i.sku, i.size",
            (since,),
        ).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        if r["open_demand"] > r["on_hand"] + r["on_order"]:
            r["signal"] = "stockout_risk"
        elif r["on_hand"] > 0 and r["units_out"] == 0 and r["open_demand"] == 0:
            r["signal"] = "slow_mover"
        else:
            r["signal"] = "ok"
        out.append(r)
    return out


@mcp.tool
def adjust_inventory(sku: str, size: str, delta: int, reason: str, agent: AgentName, ticket_id: int | None = None) -> dict:
    """Change on-hand stock by `delta` (negative = units leave the shelf for an order/shrinkage; positive =
    count correction). Requires a reason; refuses to go below zero. Use receive_purchase_order for deliveries."""
    if delta == 0 or not reason.strip():
        return {"ok": False, "error": "non-zero delta and a reason are required"}
    with _db() as conn:
        row = conn.execute("SELECT qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone()
        if row is None:
            return {"ok": False, "error": f"{sku} size {size} not carried"}
        new_qty = row["qty"] + delta
        if new_qty < 0:
            return {"ok": False, "error": f"only {row['qty']} on hand; cannot remove {-delta}"}
        conn.execute("UPDATE inventory SET qty = ? WHERE sku = ? AND size = ?", (new_qty, sku, size))
        conn.execute(
            "INSERT INTO inventory_movements (sku, size, delta, reason, ticket_id, agent, shop_date, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sku, size, delta, reason.strip(), ticket_id, agent, _today(conn).isoformat(), _now()),
        )
        return {"ok": True, "sku": sku, "size": size, "before": row["qty"], "after": new_qty}


@mcp.tool
def list_vendors() -> list[dict]:
    """All vendors with specialty, lead days, whether they will ship today, open invoice total, and ETA if ordered today."""
    with _db() as conn:
        today = _today(conn)
        out = []
        for v in conn.execute("SELECT * FROM vendors ORDER BY id"):
            owed = sum(r["amount"] for r in _open_invoices(conn, v["id"]))
            out.append({
                **dict(v), "will_ship": owed == 0, "open_invoice_total": round(owed, 2),
                "eta_if_ordered_today": (today + timedelta(days=v["lead_days"])).isoformat() if owed == 0 else None,
            })
        return out


@mcp.tool
def check_vendor_restock(vendor_id: int) -> dict:
    """Will this vendor ship today? Lists the open invoices blocking it (vendors refuse to ship with any open
    invoice) and the ETA (shop date + lead_days) now and once unblocked."""
    with _db() as conn:
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            return {"found": False, "vendor_id": vendor_id}
        today = _today(conn)
        blocking = [
            {"invoice_id": r["id"], "amount": r["amount"], "due_date": r["due_date"],
             "overdue": date.fromisoformat(r["due_date"]) < today, "description": r["description"]}
            for r in _open_invoices(conn, vendor_id)
        ]
    eta = (today + timedelta(days=vendor["lead_days"])).isoformat()
    return {
        "found": True, "vendor_id": vendor["id"], "name": vendor["name"], "specialty": vendor["specialty"],
        "lead_days": vendor["lead_days"], "today": today.isoformat(), "will_ship": not blocking,
        "blocking_invoices": blocking, "amount_to_unblock": round(sum(i["amount"] for i in blocking), 2),
        "eta_if_ordered_today": eta if not blocking else None, "eta_if_unblocked_today": eta,
    }


@mcp.tool
def create_purchase_order(vendor_id: int, sku: str, size: str, qty: int, agent: AgentName, ticket_id: int | None = None) -> dict:
    """Request an internal restock order (no real vendor is contacted). Creates the PO as 'pending_approval'
    plus a human approval request; it is placed only when a human approves. Refuses if the vendor has an open
    invoice, if estimated cost (unit_cost x qty) exceeds cash on hand, or if an identical open PO exists."""
    if qty <= 0:
        return {"ok": False, "error": "qty must be positive"}
    with _db() as conn:
        today = _today(conn)
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            return {"ok": False, "error": f"vendor {vendor_id} not found"}
        if conn.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
            return {"ok": False, "error": f"{sku} size {size} not carried"}
        blocking = _open_invoices(conn, vendor_id)
        if blocking:
            return {"ok": False, "status": "refused", "error": "vendor will not ship: open invoice(s)",
                    "blocking_invoice_ids": [r["id"] for r in blocking]}
        dup = conn.execute(
            "SELECT id, status FROM purchase_orders WHERE vendor_id = ? AND sku = ? AND size = ? AND status IN ('pending_approval', 'placed') "
            "AND COALESCE(ticket_id, -1) = COALESCE(?, -1)", (vendor_id, sku, size, ticket_id),
        ).fetchone()
        if dup:
            return {"ok": False, "status": "duplicate", "error": f"PO {dup['id']} ({dup['status']}) already covers this", "po_id": dup["id"]}
        price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if price is None:
            return {"ok": False, "error": f"no unit cost on file for {sku}"}
        est_cost = round(price["unit_cost"] * qty, 2)
        cash = _cash(conn) or 0.0
        if est_cost > cash:
            return {"ok": False, "status": "refused", "error": "insufficient cash for this order",
                    "est_cost": est_cost, "cash": cash, "max_affordable_qty": int(cash // price["unit_cost"])}
        eta = (today + timedelta(days=vendor["lead_days"])).isoformat()
        cur = conn.execute(
            "INSERT INTO purchase_orders (vendor_id, sku, size, qty, est_cost, ordered_on, eta, status, ticket_id, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?)",
            (vendor_id, sku, size, qty, est_cost, today.isoformat(), eta, ticket_id, agent),
        )
        appr = conn.execute(
            "INSERT INTO approval_requests (kind, ticket_id, ref_kind, ref_id, amount, details, requested_by, requested_at) "
            "VALUES ('purchase', ?, 'purchase_order', ?, ?, ?, ?, ?)",
            (ticket_id, cur.lastrowid, est_cost, f"PO {cur.lastrowid}: {qty} x {sku} {size} from {vendor['name']}, "
             f"est. {est_cost:.2f}, ETA {eta} if approved today", agent, _now()),
        )
        return {"ok": True, "po_id": cur.lastrowid, "approval_id": appr.lastrowid, "status": "pending_approval",
                "vendor": vendor["name"], "sku": sku, "size": size, "qty": qty, "est_cost": est_cost,
                "eta_if_approved_today": eta, "note": "awaiting human approval; internal record only; vendor bills on receipt"}


@mcp.tool
def list_purchase_orders(status: Literal["pending_approval", "placed", "received", "rejected", "all"] = "placed") -> list[dict]:
    """List restock purchase orders by status."""
    with _db() as conn:
        sql, args = "SELECT * FROM purchase_orders", ()
        if status != "all":
            sql, args = sql + " WHERE status = ?", (status,)
        return _rows(conn.execute(sql + " ORDER BY id", args))


@mcp.tool
def receive_purchase_order(po_id: int, agent: AgentName) -> dict:
    """Receive a delivered PO: adds units to inventory and books the vendor's invoice (due in 30 days) as an
    open payable. Refuses before the PO's ETA (shop date) or if already received."""
    with _db() as conn:
        today = _today(conn)
        po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if po is None:
            return {"ok": False, "error": f"PO {po_id} not found"}
        if po["status"] != "placed":
            return {"ok": False, "error": f"PO {po_id} is already {po['status']}"}
        if date.fromisoformat(po["eta"]) > today:
            return {"ok": False, "error": f"not delivered yet; ETA {po['eta']}, today {today.isoformat()}"}
        conn.execute("UPDATE inventory SET qty = qty + ? WHERE sku = ? AND size = ?", (po["qty"], po["sku"], po["size"]))
        conn.execute(
            "INSERT INTO inventory_movements (sku, size, delta, reason, ticket_id, agent, shop_date, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (po["sku"], po["size"], po["qty"], f"received PO {po_id}", po["ticket_id"], agent, today.isoformat(), _now()),
        )
        inv = conn.execute(
            "INSERT INTO invoices (vendor_id, amount, due_date, status, description) VALUES (?, ?, ?, 'open', ?)",
            (po["vendor_id"], po["est_cost"], (today + timedelta(days=30)).isoformat(),
             f"PO {po_id}: {po['qty']} x {po['sku']} {po['size']}"),
        )
        conn.execute("UPDATE purchase_orders SET status = 'received', invoice_id = ? WHERE id = ?", (inv.lastrowid, po_id))
        return {"ok": True, "po_id": po_id, "units_added": po["qty"], "invoice_id": inv.lastrowid, "invoice_amount": po["est_cost"]}


# ---------------------------------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------------------------------

@mcp.tool
def get_cash_position(horizon_days: int = 30) -> dict:
    """Cash on hand vs. obligations due within `horizon_days` of the shop date: open invoices (incl. overdue),
    rent, and open POs not yet invoiced. Returns projected balance and any shortfall."""
    with _db() as conn:
        today = _today(conn)
        horizon = today + timedelta(days=horizon_days)
        cash = _cash(conn) or 0.0
        invoices = [
            {"invoice_id": r["id"], "vendor_id": r["vendor_id"], "amount": r["amount"], "due_date": r["due_date"],
             "overdue": date.fromisoformat(r["due_date"]) < today}
            for r in _open_invoices(conn) if date.fromisoformat(r["due_date"]) <= horizon
        ]
        rent = [
            {"lease_id": r["id"], "amount": r["monthly_rent"], "due_date": r["next_due"]}
            for r in conn.execute("SELECT * FROM leases") if date.fromisoformat(r["next_due"]) <= horizon
        ]
        pos = [
            {"po_id": r["id"], "amount": r["est_cost"], "eta": r["eta"]}
            for r in conn.execute("SELECT * FROM purchase_orders WHERE status IN ('pending_approval', 'placed')")
        ]
    total = round(sum(x["amount"] for x in invoices + rent + pos), 2)
    projected = round(cash - total, 2)
    return {
        "today": today.isoformat(), "horizon_end": horizon.isoformat(), "cash_on_hand": cash,
        "obligations": {"invoices": invoices, "rent": rent, "open_purchase_orders": pos}, "total_obligations": total,
        "projected_balance": projected, "shortfall": max(-projected, 0),
    }


@mcp.tool
def list_invoices(status: Literal["open", "paid", "all"] = "open") -> list[dict]:
    """Vendor invoices with vendor name and an overdue flag (due_date before the shop date)."""
    with _db() as conn:
        today = _today(conn)
        sql, args = "SELECT i.*, v.name AS vendor FROM invoices i JOIN vendors v ON v.id = i.vendor_id", ()
        if status != "all":
            sql, args = sql + " WHERE i.status = ?", (status,)
        return [
            {**dict(r), "overdue": r["status"] == "open" and date.fromisoformat(r["due_date"]) < today}
            for r in conn.execute(sql + " ORDER BY i.due_date", args)
        ]


@mcp.tool
def list_payments(limit: int = 20) -> list[dict]:
    """Most recent recorded payments (each was human-approved)."""
    with _db() as conn:
        return _rows(conn.execute("SELECT * FROM payments ORDER BY id DESC LIMIT ?", (limit,)))


@mcp.tool
def preview_payment(kind: Literal["invoice", "lease"], ref_id: int) -> dict:
    """What paying this invoice or lease would do, without paying: amount, payee, due date, overdue,
    balance before/after, whether cash covers it, prior payments on it, and any pending approval."""
    with _db() as conn:
        today = _today(conn)
        bill, err = _bill(conn, kind, ref_id)
        if err:
            return {"ok": False, "error": err}
        cash = _cash(conn) or 0.0
        prior = _rows(conn.execute(
            "SELECT id, amount, paid_at, approved_by FROM payments WHERE kind = ? AND ref_id = ? ORDER BY id DESC LIMIT 3",
            (kind, ref_id)))
        pending = conn.execute(
            "SELECT id FROM approval_requests WHERE kind = 'payment' AND ref_kind = ? AND ref_id = ? AND status = 'pending'",
            (kind, ref_id)).fetchone()
    return {
        "ok": True, "kind": kind, "ref_id": ref_id, **bill,
        "days_until_due": (date.fromisoformat(bill["due_date"]) - today).days,
        "overdue": date.fromisoformat(bill["due_date"]) < today,
        "balance_before": cash, "balance_after": round(cash - bill["amount"], 2),
        "sufficient_cash": cash >= bill["amount"], "prior_payments": prior,
        "pending_approval_id": pending["id"] if pending else None,
    }


@mcp.tool
def request_payment_approval(kind: Literal["invoice", "lease"], ref_id: int, reason: str, agent: AgentName,
                             ticket_id: int | None = None) -> dict:
    """Ask a human to approve paying an invoice or rent. Does NOT pay. Refuses if cash cannot cover it, if the
    invoice is already paid, or if a pending request for the same bill exists (returns that id)."""
    if not reason.strip():
        return {"ok": False, "error": "reason is required"}
    with _db() as conn:
        bill, err = _bill(conn, kind, ref_id)
        if err:
            return {"ok": False, "error": err}
        pending = conn.execute(
            "SELECT id FROM approval_requests WHERE kind = 'payment' AND ref_kind = ? AND ref_id = ? AND status = 'pending'",
            (kind, ref_id)).fetchone()
        if pending:
            return {"ok": False, "status": "duplicate", "approval_id": pending["id"], "error": "already awaiting approval"}
        cash = _cash(conn) or 0.0
        if cash < bill["amount"]:
            return {"ok": False, "status": "refused", "error": "insufficient cash", "amount": bill["amount"], "cash": cash}
        cur = conn.execute(
            "INSERT INTO approval_requests (kind, ticket_id, ref_kind, ref_id, amount, details, requested_by, requested_at) "
            "VALUES ('payment', ?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, kind, ref_id, bill["amount"], f"Pay {bill['payee']} {bill['amount']:.2f} ({bill['description']}, "
             f"due {bill['due_date']}). {reason.strip()}", agent, _now()),
        )
        return {"ok": True, "approval_id": cur.lastrowid, "status": "pending", "amount": bill["amount"],
                "note": "a human must approve on the dashboard; nothing has been paid"}


# ---------------------------------------------------------------------------------------------------
# Customer service and pricing
# ---------------------------------------------------------------------------------------------------

@mcp.tool
def get_catalog() -> list[dict]:
    """Customer-facing catalog: each product's SKU, name, list price, and per-size availability (no costs)."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT i.sku, i.name, i.size, i.qty, p.list_price FROM inventory i LEFT JOIN pricing p ON p.sku = i.sku "
            "ORDER BY i.sku, i.size"
        ).fetchall()
    catalog: dict[str, dict] = {}
    for r in rows:
        item = catalog.setdefault(r["sku"], {"sku": r["sku"], "name": r["name"], "list_price": r["list_price"], "sizes": {}})
        item["sizes"][r["size"]] = r["qty"]
    return list(catalog.values())


@mcp.tool
def quote_order(sku: str, size: str, qty: int, discount_pct: float = 0) -> dict:
    """Price an order: unit and total price at list and after `discount_pct`, cost, margin $ and %, and stock
    coverage. Any discount > 0 requires human approval (discount policy is not yet set)."""
    if qty <= 0 or not 0 <= discount_pct < 100:
        return {"ok": False, "error": "qty must be positive and 0 <= discount_pct < 100"}
    with _db() as conn:
        p = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone()
        inv = conn.execute("SELECT qty FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone()
    if p is None or inv is None:
        return {"ok": False, "error": f"{sku} size {size} not carried"}
    unit = round(p["list_price"] * (1 - discount_pct / 100), 2)
    total, cost = round(unit * qty, 2), round(p["unit_cost"] * qty, 2)
    return {
        "ok": True, "sku": sku, "size": size, "qty": qty, "list_unit": p["list_price"], "unit_price": unit,
        "list_total": round(p["list_price"] * qty, 2), "total": total, "total_cost": cost,
        "margin": round(total - cost, 2), "margin_pct": round((total - cost) / total * 100, 1) if total else None,
        "on_hand": inv["qty"], "can_fill_now": inv["qty"] >= qty, "requires_human_approval": discount_pct > 0,
    }


@mcp.tool
def request_discount_approval(ticket_id: int, sku: str, size: str, qty: int, discount_pct: float, reason: str,
                              agent: AgentName) -> dict:
    """Ask a human to approve a discount on a ticket's order. Records the quote's margin with the request.
    Refuses a second pending discount request on the same ticket."""
    q = quote_order(sku, size, qty, discount_pct)
    if not q["ok"]:
        return q
    if discount_pct <= 0 or not reason.strip():
        return {"ok": False, "error": "discount_pct > 0 and a reason are required"}
    with _db() as conn:
        pending = conn.execute(
            "SELECT id FROM approval_requests WHERE kind = 'discount' AND ticket_id = ? AND status = 'pending'", (ticket_id,)
        ).fetchone()
        if pending:
            return {"ok": False, "status": "duplicate", "approval_id": pending["id"], "error": "already awaiting approval"}
        cur = conn.execute(
            "INSERT INTO approval_requests (kind, ticket_id, ref_kind, amount, details, requested_by, requested_at) "
            "VALUES ('discount', ?, 'ticket', ?, ?, ?, ?)",
            (ticket_id, q["list_total"] - q["total"],
             f"{discount_pct:g}% off {qty} x {sku} {size}: {q['total']:.2f} vs list {q['list_total']:.2f}, "
             f"margin {q['margin']:.2f} ({q['margin_pct']}%). {reason.strip()}", agent, _now()),
        )
        return {"ok": True, "approval_id": cur.lastrowid, "status": "pending", "quote": q}


@mcp.tool
def draft_customer_reply(ticket_id: int, body: str, agent: AgentName) -> dict:
    """Save a reply to the ticket's requester as a DRAFT for human review. Nothing is ever sent to customers."""
    if not body.strip():
        return {"ok": False, "error": "body is required"}
    with _db() as conn:
        if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"ok": False, "error": f"ticket {ticket_id} not found"}
        conn.execute("UPDATE customer_replies SET status = 'superseded' WHERE ticket_id = ? AND status = 'draft'", (ticket_id,))
        cur = conn.execute(
            "INSERT INTO customer_replies (ticket_id, body, drafted_by, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, body.strip(), agent, _now()),
        )
        return {"ok": True, "draft_id": cur.lastrowid, "status": "draft", "sent": False}


# ---------------------------------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------------------------------

@mcp.tool
def list_leases() -> list[dict]:
    """Leases with rent, next due date, days until due, overdue flag, and the most recent rent payment."""
    with _db() as conn:
        today = _today(conn)
        out = []
        for r in conn.execute("SELECT * FROM leases ORDER BY id"):
            last = conn.execute(
                "SELECT amount, paid_at, approved_by FROM payments WHERE kind = 'lease' AND ref_id = ? ORDER BY id DESC LIMIT 1",
                (r["id"],)).fetchone()
            due = date.fromisoformat(r["next_due"])
            out.append({**{k: v for k, v in dict(r).items() if v is not None},
                        "days_until_due": (due - today).days, "overdue": due < today,
                        "last_payment": dict(last) if last else None})
        return out


@mcp.tool
def report_facility_issue(issue: str, severity: Literal["low", "medium", "high", "urgent"], agent: AgentName,
                          lease_id: int | None = None, ticket_id: int | None = None) -> dict:
    """Log a facility issue (maintenance, cleanliness, safety, signage, lease terms) for follow-up."""
    if not issue.strip():
        return {"ok": False, "error": "issue is required"}
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO facility_issues (lease_id, ticket_id, issue, severity, reported_by, reported_on) VALUES (?, ?, ?, ?, ?, ?)",
            (lease_id, ticket_id, issue.strip(), severity, agent, _today(conn).isoformat()),
        )
        return {"ok": True, "issue_id": cur.lastrowid}


@mcp.tool
def list_facility_issues(status: Literal["open", "closed", "all"] = "open") -> list[dict]:
    """Facility issues by status."""
    with _db() as conn:
        sql, args = "SELECT * FROM facility_issues", ()
        if status != "all":
            sql, args = sql + " WHERE status = ?", (status,)
        return _rows(conn.execute(sql + " ORDER BY id", args))


# ---------------------------------------------------------------------------------------------------
# Human-only (dashboard). Never exposed to agents.
# ---------------------------------------------------------------------------------------------------

@mcp.tool
def decide_approval(approval_id: int, decision: Literal["approve", "reject"], decided_by: str, note: str = "") -> dict:
    """HUMAN ONLY. Approve or reject a pending request. Approving a payment executes it atomically: rechecks
    cash (refuses if insufficient), inserts into payments, debits cash, and marks the invoice paid or advances
    the lease's next_due one month. Approving a purchase places the PO (rechecks vendor standing and cash;
    ETA from today). Approving a discount only records the approval."""
    if not decided_by.strip() or decided_by.strip().lower() in AGENTS:
        return {"ok": False, "error": "decided_by must be a human's name"}
    with _db() as conn:
        today = _today(conn)
        req = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        if req is None:
            return {"ok": False, "error": f"approval {approval_id} not found"}
        if req["status"] != "pending":
            return {"ok": False, "error": f"approval {approval_id} is already {req['status']}"}
        stamp = (decided_by.strip(), _now(), note.strip() or None, approval_id)
        if decision == "reject":
            conn.execute("UPDATE approval_requests SET status='rejected', decided_by=?, decided_at=?, decision_note=? WHERE id=?", stamp)
            if req["kind"] == "purchase":
                conn.execute("UPDATE purchase_orders SET status = 'rejected' WHERE id = ?", (req["ref_id"],))
            return {"ok": True, "approval_id": approval_id, "status": "rejected"}
        if req["kind"] == "purchase":
            po = conn.execute(
                "SELECT p.*, v.lead_days FROM purchase_orders p JOIN vendors v ON v.id = p.vendor_id WHERE p.id = ?", (req["ref_id"],)
            ).fetchone()
            cash = _cash(conn) or 0.0
            reason = (None if po and po["status"] == "pending_approval" else "PO is not awaiting approval") \
                or ("vendor has an open invoice" if _open_invoices(conn, po["vendor_id"]) else None) \
                or ("insufficient cash" if cash < po["est_cost"] else None)
            if reason:
                conn.execute("UPDATE approval_requests SET status='refused', decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                             (decided_by.strip(), _now(), reason, approval_id))
                return {"ok": False, "approval_id": approval_id, "status": "refused", "error": reason, "cash": cash}
            eta = (today + timedelta(days=po["lead_days"])).isoformat()
            conn.execute("UPDATE purchase_orders SET status = 'placed', ordered_on = ?, eta = ? WHERE id = ?",
                         (today.isoformat(), eta, po["id"]))
            conn.execute("UPDATE approval_requests SET status='executed', decided_by=?, decided_at=?, decision_note=? WHERE id=?", stamp)
            if req["ticket_id"]:
                _append_note(conn, req["ticket_id"], decided_by.strip(), f"PO {po['id']} approved and placed; ETA {eta}")
            return {"ok": True, "approval_id": approval_id, "status": "executed", "po_id": po["id"], "eta": eta}
        if req["kind"] != "payment":
            conn.execute("UPDATE approval_requests SET status='approved', decided_by=?, decided_at=?, decision_note=? WHERE id=?", stamp)
            return {"ok": True, "approval_id": approval_id, "status": "approved"}

        kind, ref_id = req["ref_kind"], req["ref_id"]
        bill, err = _bill(conn, kind, ref_id)
        cash = _cash(conn)
        if err or cash is None or cash < bill["amount"]:
            reason = err or "insufficient cash"
            conn.execute("UPDATE approval_requests SET status='refused', decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                         (decided_by.strip(), _now(), reason, approval_id))
            return {"ok": False, "approval_id": approval_id, "status": "refused", "error": reason, "cash": cash}
        pay = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, 'checking', ?, ?)",
            (kind, ref_id, bill["amount"], today.isoformat(), decided_by.strip()),
        )
        conn.execute("UPDATE cash_accounts SET balance = balance - ?, date = ? WHERE name = 'checking'", (bill["amount"], today.isoformat()))
        result = {"ok": True, "approval_id": approval_id, "status": "executed", "payment_id": pay.lastrowid,
                  "amount": bill["amount"], "balance_after": round(cash - bill["amount"], 2)}
        if kind == "invoice":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (ref_id,))
        else:
            next_due = _add_month(date.fromisoformat(bill["due_date"])).isoformat()
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due, ref_id))
            result["lease_next_due"] = next_due
        conn.execute(
            "UPDATE approval_requests SET status='executed', decided_by=?, decided_at=?, decision_note=?, payment_id=? WHERE id=?",
            (decided_by.strip(), _now(), note.strip() or None, pay.lastrowid, approval_id),
        )
        if req["ticket_id"]:
            _append_note(conn, req["ticket_id"], decided_by.strip(), f"payment {pay.lastrowid} executed ({bill['amount']:.2f})")
        return result


@mcp.tool
def resolve_ticket(ticket_id: int, resolved_by: str, note: str) -> dict:
    """HUMAN ONLY. A human marks a ticket resolved from the dashboard, with a signed note."""
    if not resolved_by.strip() or resolved_by.strip().lower() in AGENTS:
        return {"ok": False, "error": "resolved_by must be a human's name"}
    if not note.strip():
        return {"ok": False, "error": "note is required"}
    with _db() as conn:
        if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"ok": False, "error": f"ticket {ticket_id} not found"}
        _append_note(conn, ticket_id, resolved_by.strip(), f"resolved by human: {note.strip()}")
        conn.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
        return {"ok": True, "ticket_id": ticket_id, "status": "resolved"}


@mcp.tool
def add_human_direction(ticket_id: int, author: str, direction: str) -> dict:
    """HUMAN ONLY. Record a human's decision or instruction on a ticket: appended to the notes as DIRECTION
    and delivered to boss's inbox. Agents carry it out on the next run, within the shop rules."""
    if not author.strip() or author.strip().lower() in AGENTS:
        return {"ok": False, "error": "author must be a human's name"}
    if not direction.strip():
        return {"ok": False, "error": "direction is required"}
    with _db() as conn:
        if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is None:
            return {"ok": False, "error": f"ticket {ticket_id} not found"}
        _append_note(conn, ticket_id, author.strip(), f"DIRECTION: {direction.strip()}")
        cur = conn.execute(
            "INSERT INTO agent_messages (created_at, ticket_id, from_agent, to_agent, kind, body) VALUES (?, ?, ?, 'boss', 'direction', ?)",
            (_now(), ticket_id, f"human:{author.strip()}", direction.strip()),
        )
        return {"ok": True, "ticket_id": ticket_id, "message_id": cur.lastrowid}


if __name__ == "__main__":
    mcp.run(show_banner=False)
