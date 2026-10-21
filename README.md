# Campus Customs Agent Team (Homework 5)

A five-agent back office for Campus Customs, a collegiate apparel shop. The agents are boss, inventory, accounting, facilities and customer service. They work shop tickets through an MCP server, and a human oversees them from a React dashboard. Payments, purchase orders and discounts move only on a human's approval.

| Piece | Where | What |
|---|---|---|
| MCP server | `mcp_server/server.py` | FastMCP. The only path to the shop database: 29 agent tools plus 3 human-only tools. |
| Agent team + API | `backend/` | PydanticAI agents (`gpt-6-luna` via Portkey) that delegate to each other, plus FastAPI routes in `main.py`. |
| Dashboard | `frontend/` | React + Vite + TypeScript, styled as a Yale college "desk". |
| Data | `data/` | `campus_customs.db` is the original (never modified); `campus_customs_new.db` is the working copy. |
| Evidence | `output/` | Harness, plan vs actual (`desk_tickets.html`), resolved tickets, board screenshots, audit trail. |

## Setup (once)
Requirements: Python 3.13+ and Node 20+.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env        # then put your Portkey key in PORTKEY_API_KEY
```

`.env` is git-ignored; never commit it.

## 1. Copy the original database to the working copy (clean run)
The agents only ever write to `data/campus_customs_new.db`. To start from the original books ($3,400 cash, invoice 501 unpaid, rent due 2026-09-02, all tickets open):

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

The MCP server recreates its coordination tables (assignments, messages, approvals, POs, drafts…) on the next connection.

## 2. Start the MCP server
The backend launches the server itself over stdio from `.mcp.json`, so you don't need a separate process for the app. To run it standalone, or to let Claude Code call the tools directly (`.mcp.json` registers it as `campus-customs`):

```bash
.venv/bin/python mcp_server/server.py
```

## 3. Start the FastAPI backend
From `backend/`:

```bash
cd backend && ../.venv/bin/uvicorn main:app --reload --port 8000
```

Routes are listed in `output/harness.md`. Interactive docs: http://localhost:8000/docs

## 4. Start the React board
In a second terminal:

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. CORS on the backend allows this origin.

## 5. Reset before a full three-ticket run
Either click **Begin a Fresh Term** in the board's left column (it calls `POST /reset`, which restores the original books and keeps the append-only audit trail), or run:

```bash
curl -X POST http://localhost:8000/reset
```

Reset is refused while a run is in progress.

## 6. Run the three tickets
1. Type your name under **Signed by** in the masthead. Approvals are signed with it.
2. Pick ticket **101** and click **Convene the Fellows**. Watch the agent cards and the Proceedings feed.
3. When the run parks a ticket, approve or reject in **Awaiting Assent**, give **Direction from the Desk** if the team asks for a decision, and reconvene. Click **Mark resolved** when you're satisfied.
4. Repeat for **102** and **103**.

Every agent step and human action is appended to `output/audit_trail.json`.

## 7. Testing one agent with Tenet (branch `tenet-bridge`)
[Tenet](https://github.com/shanehaynes/tenet) tests an agent against its written rules. `POST /tenet/ask` runs one agent on one operator request, the same way the board's "ask an agent" does, and returns its report, every tool call it made (from the audit trail) and its token usage. By default each request first restores the original books, so every test starts from the same state; a request that arrives while another is running gets `409 {"error": "busy"}`.

Run the backend for Tenet against separate, git-ignored copies of the books and the audit trail, so the homework evidence stays untouched:

```bash
cd backend && CAMPUS_DB_PATH=data/tenet_working.db CAMPUS_AUDIT_PATH=output/tenet_audit_trail.json ../.venv/bin/uvicorn main:app --port 8000
```

```bash
curl -s -X POST http://localhost:8000/tenet/ask -H 'content-type: application/json' -d '{"agent": "customer_service", "message": "Do you have navy hoodies in stock?"}'
```

The key is read from `.env`, or from `../.env` when the repo has none.

## Shop rules the system enforces
1. `desk.date_today` is "today".
2. Vendor lead times come from `vendors`.
3. Vendors won't ship with an open invoice.
4. Payments and purchases need human approval.
5. Transactions are refused when cash can't cover them.
6. No real customers or vendors are ever contacted: replies are drafts and POs are internal records.

## Key documents
- `output/harness.md`: tables, MCP tools by agent, the five agents, API routes, dashboard, safety, token efficiency.
- `output/desk_tickets.html`: plan vs actual for each ticket, plus the Cash and Reflection tabs. Double-click to open.
- `output/resolved_board.html`: dashboard screenshots of each resolved ticket.
- `output/design.md`: dashboard design rationale.
- `AI_prompts.md`: every prompt used to build this.
