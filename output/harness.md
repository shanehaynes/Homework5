# Campus Customs Harness

The agent team's reference: shop database, MCP tools, the five agents, API routes, dashboard, and safety rules.

Contents:
1. **Database tables:** the nine shop tables below, plus the seven coordination tables in *Coordination tables*.
2. **MCP tools:** the first three (Problem 3), then the full 32-tool matrix in *Agents and their MCP tools*.
3. **The five agents:** *Problem 5: Agent team*, covering prompts, delegation, the agent loop, and the audit trail.
4. **Token efficiency.**
5. **API routes:** *Backend routes*.
6. **Dashboard:** *Dashboard (Problem 8)*.
7. **Safety rules:** *Safety*, plus *Verified in the live runs*.

Live run results are in `output/desk_tickets.html` (Actual and Cash tabs), `output/resolved_tickets.json`, `output/resolved_board.html`, and `output/audit_trail.json`.


Working copy: `data/campus_customs_new.db`. Original: `data/campus_customs.db` (never modified).

## desk
Fields: `date_today`, `notes`

Why it matters: Sets the shop's "today" (2026-08-31), the clock every agent uses to judge what is due or overdue.

## inventory
Fields: `sku`, `name`, `size`, `qty`, `location` (PK: `sku` + `size`)

Why it matters: Inventory checks stock by SKU and size before Customer Service promises an order or the Boss approves a bulk sale.

## pricing
Fields: `sku`, `unit_cost`, `list_price`

Why it matters: Gives cost and list price per SKU, so agents can value orders and bound any discount by margin.

## vendors
Fields: `id`, `name`, `specialty`, `lead_days`

Why it matters: Tells Inventory who can restock what and how many days it takes, which sets realistic fulfillment dates.

## invoices
Fields: `id`, `vendor_id`, `amount`, `due_date`, `status`, `description`

Why it matters: Accounting tracks what the shop owes. A vendor with an open unpaid invoice will not ship, so this table gates restocking.

## leases
Fields: `id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`

Why it matters: Facilities tracks rent obligations and due dates. A paid rent moves `next_due` forward one month.

## cash_accounts
Fields: `name`, `balance`, `date`

Why it matters: The cash on hand that every payment is checked against. Payments larger than the balance are refused.

## payments
Fields: `id`, `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`

Why it matters: The audit trail of human-approved payments. Each row links to an invoice or lease via `kind` + `ref_id`.

## tickets
Fields: `id`, `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`, `invoice_id`, `status`, `notes`, `created_at`

Why it matters: The work queue. The Boss reads each ticket's `type` to route it to the right agent, and the ticket's foreign keys point at the inventory, lease, or invoice involved.

## Coordination tables (added by the MCP server, Problem 5+)
The MCP server creates these on every connection with `CREATE TABLE IF NOT EXISTS`, so they survive `/reset`. The nine shop tables keep their original schema.

| Table | Fields | Why it matters |
|---|---|---|
| `ticket_assignments` | ticket_id, owner, assigned_by, assigned_at | One owner per ticket; the duplicate-work guard. |
| `agent_messages` | id, created_at, ticket_id, from_agent, to_agent, kind, body, read_by_recipient, read_by_boss | Team communication. Boss is cc'd on everything; human directions arrive here too. |
| `approval_requests` | id, kind (payment / purchase / discount), ticket_id, ref_kind, ref_id, amount, details, requested_by, requested_at, status, decided_by, decided_at, decision_note, payment_id | The human-approval queue the dashboard shows. |
| `purchase_orders` | id, vendor_id, sku, size, qty, est_cost, ordered_on, eta, status (pending_approval / placed / received / rejected), ticket_id, created_by, invoice_id | Restock commitments; placed only after a human approves. |
| `inventory_movements` | id, sku, size, delta, reason, ticket_id, agent, shop_date, created_at | Stock audit and the demand-signal history. |
| `customer_replies` | id, ticket_id, body, status (draft / superseded), drafted_by, created_at | Reply drafts; nothing is ever sent. |
| `facility_issues` | id, lease_id, ticket_id, issue, severity, status, reported_by, reported_on | Facilities' maintenance and quality log. |

# MCP Tools (Problem 3: first three)

Server: `mcp_server/server.py` (FastMCP, name `campus-customs`). Every agent uses these three tools against `data/campus_customs_new.db`.

## check_stock(sku, size, qty=1)
Reads: `inventory` (row matching `sku` + `size`: `qty`, `location`, `name`) joined to `pricing` (`unit_cost`, `list_price`). Writes nothing.

Unlocks: **Ticket 103** (Yale AI Club, 20 × CC-HOOD-NAVY size M at a bulk discount) and **Ticket 101** (1 × CC-TEE-WHITE size S).

Why: For 103, it returns `on_hand` 8 against a request for 20 (`shortfall` 12), plus the $22 cost and $58 list price, so the Boss can decide how many to sell now and how far any discount can go before it eats the margin. For 101, it returns `on_hand` 0, which proves the tee has to come from a vendor restock rather than the shelf.

## check_vendor_restock(vendor_id)
Reads: `vendors` (`name`, `specialty`, `lead_days`), `invoices` (rows where `vendor_id` matches and `status = 'open'`: `amount`, `due_date`), and `desk.date_today` to flag overdue invoices and compute the ETA. Writes nothing.

Unlocks: **Ticket 101** (the S tee, which links to `invoice_id` 501), and the restock half of **Ticket 103** (the 12-hoodie shortfall).

Why: Bulldog Print Co (vendor 1, apparel reprint, 5-day lead) has invoice 501 open ($840, due 2026-08-28, overdue as of 2026-08-31). The tool returns `will_ship: false`, names 501 as the blocker, and gives `eta_if_unblocked_today` = 2026-09-05. That is the exact chain Customer Service needs to give the customer an honest date and the reason behind it.

## pay_bill(kind, ref_id, approved_by=None, account="checking")
> Superseded in Problem 5. Split into `preview_payment` and `request_payment_approval` (agents) and `decide_approval` (human only), so the approver can no longer be a free-text argument an agent could fill in.

Reads: `desk.date_today`, `cash_accounts.balance`, and either `invoices` (`amount`, `status`, `due_date`) for `kind="invoice"` or `leases` (`monthly_rent`, `next_due`) for `kind="lease"`.

Writes, only when `approved_by` is set and cash covers the bill:
- inserts a row into `payments`
- debits `cash_accounts.balance`
- sets `invoices.status = 'paid'`, or advances `leases.next_due` by one month

Unlocks: **Ticket 102** (Elm City Properties rent, lease 1, $2,400 due 2026-09-02) and the payment of invoice 501 that **Ticket 101** depends on.

Why: Called without `approved_by`, it returns a preview with no writes (amount, balance before/after, `sufficient_cash`, status `needs_approval`), which is the approval request a human signs on the dashboard. Called with a name, it records the payment in one transaction, so rule 4 (human approval, tables updated) and rule 5 (refused if balance < amount) are both enforced in the database layer rather than left to the agent's judgment.

Guardrail note: the MCP layer cannot verify that `approved_by` came from a human. The FastAPI backend must only pass `approved_by` after an approval click on the dashboard, and must strip it from any agent-initiated call.

## Payment authority (decided in Problem 4)
Agents cannot execute payments. They can preview a payment and file an approval request. Only the human-only `decide_approval` tool, called from the dashboard, executes a payment. The one exception was the Problem 4 smoke test, which Shane approved: invoice 501 ($840) and the lease 1 rent ($2,400) were paid, leaving checking at $160. Evidence is in `output/mcp_smoke.json`.


# Problem 5: Agent team

Stack: PydanticAI agents in `backend/` (one spec file per agent plus a shared runtime in `team.py`).
- **Model:** `gpt-6-luna` through Portkey (`https://api.portkey.ai/v1`, key in `.env`). The Portkey check on 2026-10-14 was served by `gpt-6-luna-global`.
- **MCP:** every agent reaches the shop only through the `campus-customs` MCP server. There is one stdio connection, built from `.mcp.json` and shared by the whole team. There is no second shop-tools layer.
- **Prompts:** `backend/prompts/`, one file per agent, plus `_team_charter.md`. The charter holds the shop rules, vendor table, collaboration protocol, values, and efficiency rules, and is prepended to every agent.
- **Data types:** `backend/models.py`:
  - `AgentSpec` and `AgentReport` (the structured output of every run)
  - `DelegationResult` and `AuditEvent`
  - `TeamRun` (shared delegation state) and `AgentDeps`
- **Entry points:** `python -m backend.team shift | ticket <id> | ask <agent> "<msg>"`. FastAPI will call the same `run_shift` / `run_ticket` / `ask_agent`.

## How the agents talk
- **`delegate(to_agent, task, ticket_id)`** is a backend tool every agent has, so any agent can hand work to any other. It runs the target agent's full loop and returns its `AgentReport`.
  - Guards: no self-delegation; no delegating to an agent already in the chain (prevents A→B→A loops); depth ≤ 3; at most 8 delegations per job.
  - Identical task + ticket within a job is shared, including while it is still in flight, so it is never done twice.
- **`send_message`** (MCP) carries FYIs and alerts. Delegations and their results are also written as messages.
- **Boss is copied on every message.** It reads unseen ones with `read_messages`. Results boss already received inline are pre-marked read, so they aren't replayed.
- **Boss is the root of every job** (`shift`, `ticket`). For direct human asks to a specialist, the backend posts the outcome to boss afterwards.
- **Ownership prevents duplicate work.** `assign_ticket` refuses when someone else owns the ticket; only boss reassigns. `update_ticket` auto-claims unowned tickets. The tools also refuse duplicate pending approvals, duplicate open POs, and duplicate payment requests.

## Agent loop and audit
`run_agent` drives PydanticAI's `agent.iter()`: model → tool calls → model … → `AgentReport`. Each run has limits: boss 14 requests / 24 tool calls; specialists 10 / 16.

Every step is appended to `output/audit_trail.json`. The file is a JSON array; entries are added in place under a file lock, and earlier entries are never rewritten. Every event records `ts`, `root_run_id`, `run_id`, `agent`, `depth`, `parent`, `ticket_id`, and `step`, plus one of these:

| Event | Data recorded |
|---|---|
| `run_start` | prompt, delegation chain, trigger |
| `model_response` | served model, finish reason, text, tool calls with args, token usage (incl. cache reads) |
| `tool_call` | tool, args as actually sent (with injected identity), result (clipped at 1,500 chars) |
| `delegation` | target, task, child run id, or the refusal reason / cache hit |
| `run_end` | final report and run usage |
| `run_error` | exception |

`root_run_id` + `parent` + `depth` reconstruct the full delegation tree after the fact.

## Agents and their MCP tools
Every agent also has the backend tool `delegate`. ✓ = visible to that agent. The backend hides everything else, and its tool-call hook blocks it as a second check.

| MCP tool | Tables (R = read, W = write) | Boss | Inventory | Accounting | Facilities | Customer Service |
|---|---|:-:|:-:|:-:|:-:|:-:|
| `get_shop_overview` | R: desk, cash_accounts, tickets, ticket_assignments, invoices, leases, approval_requests, inventory | ✓ | ✓ | ✓ | ✓ | ✓ |
| `list_tickets` | R: tickets, ticket_assignments | ✓ | ✓ | ✓ | ✓ | ✓ |
| `get_ticket` | R: tickets, ticket_assignments, agent_messages, approval_requests, purchase_orders, customer_replies, facility_issues | ✓ | ✓ | ✓ | ✓ | ✓ |
| `assign_ticket` | R: tickets, desk · W: ticket_assignments, tickets.notes | ✓ | ✓ | ✓ | ✓ | ✓ |
| `update_ticket` (any agent notes; owner/boss sets status) | R: desk · W: tickets (notes, status), ticket_assignments | ✓ | ✓ | ✓ | ✓ | ✓ |
| `send_message` | W: agent_messages | ✓ | ✓ | ✓ | ✓ | ✓ |
| `read_messages` | R/W (read flags): agent_messages | ✓ | ✓ | ✓ | ✓ | ✓ |
| `list_approvals` | R: approval_requests | ✓ | ✓ | ✓ | ✓ | ✓ |
| `check_stock` | R: inventory, pricing, purchase_orders | | ✓ | | | ✓ |
| `list_inventory` | R: inventory, pricing, purchase_orders | ✓ | ✓ | | | |
| `get_demand_signals` | R: inventory, purchase_orders, tickets, inventory_movements, desk | | ✓ | | | |
| `adjust_inventory` | R: desk · W: inventory, inventory_movements | | ✓ | | | |
| `list_vendors` | R: vendors, invoices, desk | ✓ | ✓ | ✓ | | |
| `check_vendor_restock` | R: vendors, invoices, desk | | ✓ | ✓ | | |
| `create_purchase_order` (files for human approval) | R: vendors, inventory, invoices, pricing, cash_accounts, desk · W: purchase_orders, approval_requests | | ✓ | | | |
| `list_purchase_orders` | R: purchase_orders | ✓ | ✓ | ✓ | | |
| `receive_purchase_order` | R: desk · W: purchase_orders, inventory, inventory_movements, invoices | | ✓ | | | |
| `get_cash_position` | R: cash_accounts, invoices, leases, purchase_orders, desk | ✓ | | ✓ | ✓ | |
| `list_invoices` | R: invoices, vendors, desk | | | ✓ | | |
| `list_payments` | R: payments | | | ✓ | ✓ | |
| `preview_payment` | R: invoices, vendors, leases, cash_accounts, payments, approval_requests, desk | | | ✓ | ✓ | |
| `request_payment_approval` | R: invoices, vendors, leases, cash_accounts · W: approval_requests | | | ✓ | | |
| `quote_order` | R: pricing, inventory | ✓ | | ✓ | | ✓ |
| `get_catalog` | R: inventory, pricing | | | | | ✓ |
| `request_discount_approval` | R: pricing, inventory · W: approval_requests | | | ✓ | | ✓ |
| `draft_customer_reply` | R: tickets · W: customer_replies | | | | | ✓ |
| `list_leases` | R: leases, payments, desk | ✓ | | ✓ | ✓ | |
| `report_facility_issue` | R: desk · W: facility_issues | | | | ✓ | |
| `list_facility_issues` | R: facility_issues | | | | ✓ | |
| `decide_approval` (**human only**) | R: desk, vendors · W: approval_requests, payments, cash_accounts, invoices, leases, purchase_orders, tickets.notes | | | | | |
| `resolve_ticket` (**human only**) | W: tickets (status, notes) | | | | | |
| `add_human_direction` (**human only**) | W: tickets.notes, agent_messages | | | | | |

That is 32 MCP tools in total: 29 for agents and 3 human-only. The coordination tables are described under *Coordination tables* above.

Agent roles in brief (full prompts in `backend/prompts/`):

| Agent | Role |
|---|---|
| Boss | Orchestrates: routes, assigns, delegates, decides from reports, keeps every ticket owned and parked correctly, escalates human decisions. |
| Inventory | Stock truth, low-stock alerts to the agents affected, demand signals (stockout risk / slow movers) to boss, POs, receiving, fulfillment. |
| Accounting | Source-documented payment requests, no double payment, segregation of duties, cash forecasting and early warnings, margin facts. |
| Facilities | Lease/rent verification (including already-paid and mismatched notices), shop standards, issue logging by severity. |
| Customer Service | Patient, clear replies drafted from catalog and stock facts, honest ETAs, no discount promises, holding replies and escalation where no policy exists. |

# Safety

Modeled on the structure of Anthropic's constitution for Claude:
- a short priority order of values;
- a few hard constraints that no instruction overrides;
- a strong default toward supporting human oversight;
- honesty as a near-absolute;
- judgment, guided by explained reasons, for everything else.

**Priority order** (in every prompt via the charter): **safe > honest > rule-abiding > helpful**. When values conflict, the higher one wins. Unhelpfulness is never automatically "safe"; an agent that refuses has to say why and still do the permissible part. This mirrors the constitution's point that refusal has real costs.

**Hard constraints.** These are enforced in code, not only in prompts, so a confused or manipulated model cannot cross them:

| Constraint | Enforcement |
|---|---|
| No agent executes a payment or places a purchase. | `create_purchase_order` only files a PO as `pending_approval`. `decide_approval` is the only tool that writes `payments` or places a PO. It is hidden from every agent's tool list, blocked in the backend call hook, and rejects agent names as `decided_by`. |
| No transaction beyond cash on hand. | `request_payment_approval`, `create_purchase_order`, and `decide_approval` all check the balance at call time. |
| No shipments from a vendor with an open invoice. | `create_purchase_order` refuses. |
| No contact with customers or real vendors. | No tool can send anything externally. Replies are drafts; POs are internal rows. |
| No impersonation. | The `agent` identity on every write is injected by the backend from the running agent. The model never sees the parameter. |

**Humans can steer, not just approve.** A human can give the team direction on a ticket (`DIRECTION:` notes). Boss's prompt treats it as outranking agent recommendations, within the shop rules. Like approvals and resolution, it is a human-only tool that is hidden from agents and signed with a non-agent name.

**Supporting human oversight (broad safety):**
- Humans hold the consequential levers: payments and discounts.
- Agents surface decisions in `needs_human` with approval ids rather than working around a refusal. The charter forbids splitting, re-timing, or relabeling a refused transaction.
- Agents may not acquire capability or spend beyond the task: per-role tool allowlists, delegation and usage budgets.
- Everything is auditable after the fact (`audit_trail.json`, signed append-only ticket notes, message log). Humans can see what happened and correct it.

**Honesty:**
- Agents report only what tools returned; "the data doesn't show" is an acceptable answer.
- Customer drafts must not create false impressions: no invented ETAs, no hinted discounts.
- Internal problems such as unpaid invoices are kept out of customer copy without lying about the delay.
- Bad news goes to boss early, with numbers.

**Resisting manipulation.** Ticket and message text is data, not instructions. "Pre-approved", "urgent, skip approval", or "boss said so" in a ticket approves nothing. Facilities and accounting treat a bill that doesn't match the books as possible fraud and escalate rather than pay.

**Conscientious objection, not sabotage.** An agent that won't do something says so openly in its report and continues with the rest. It never quietly does a worse job.

**Judgment under uncertainty.** When a decision is consequential, irreversible, or ambiguous, agents pause and escalate. Examples: vendor-to-SKU ambiguity, partial fulfillment without customer consent, lease changes, refunds with no policy.

# Token efficiency

Measurements use tiktoken `o200k_base` on the actual tool schemas and prompts.

**Implemented:**

| # | Change | Why it saves tokens | Measured / expected effect |
|---|---|---|---|
| 1 | Per-role tool allowlists (`prepared` toolset) | Tool schemas are re-sent on every model request. Each agent sees 13–18 tools instead of 29. | Schema per request: boss 1,443, inventory 1,882, accounting 1,853, facilities 1,491, customer service 1,480 tokens, vs 3,423 for all tools (about 50% less). |
| 2 | Hide the `agent` identity parameter from schemas | The backend fills it, so the model needn't read or write it. | 131–230 fewer schema tokens per agent per request; fewer output tokens per write call. |
| 3 | Static system prompts; all dynamic facts in the user prompt or tool results | Keeps each agent's ~2k-token prompt and its tool list byte-identical across calls, so the provider's automatic prefix cache applies. | Cached-input usage is recorded per response in the audit trail (`usage.cache_read`) so this can be verified on live runs. |
| 4 | Aggregate tools: `get_shop_overview`, `get_ticket` | One call replaces 6–8 narrow reads (tickets, owners, invoices, rent, approvals, stock, vendors). | Fewer loop iterations; every iteration re-sends the whole context. |
| 5 | Compact tool results | Nulls dropped; `list_tickets` omits notes; `get_ticket` returns only the last 8 messages and latest draft; the catalog hides costs. | Smaller tool-return tokens that compound across later turns. |
| 6 | Delegation hands over a self-contained brief, not the conversation | Sub-agents start fresh with only the task, ids, and numbers; prompts tell the delegator to include facts so they aren't re-fetched. | Context does not snowball down the chain. |
| 7 | Delegation dedupe, including in-flight tasks, plus cycle, depth and count guards | Identical delegations share one result; A→B→A loops are refused immediately. | Verified offline: a duplicate parallel delegation was served from cache and a cycle was refused. |
| 8 | Inbox never replays delivered messages | Delegations and results the recipient already got inline are stored as read. | Boss's `read_messages` returns only news. |
| 9 | Hard usage limits per run | `request_limit` / `tool_calls_limit` cap runaway loops. | Bounded worst-case cost per job. |
| 10 | Short structured output (`AgentReport`, summary ≤ 60 words) | Reports flow back into the caller's context. | Small, predictable hand-backs. |

**Vetted and rejected:**
- **Cheaper model for routine agents.** You mandated `gpt-6-luna` for all agents.
- **Dropping boss from the CC.** It's a requirement. Being CC'd costs nothing until boss reads, and read flags keep reads small.
- **LLM summarization of long histories.** Each summary is an extra model call. Runs are short and isolated per delegation, so there is nothing long to summarize.
- **Cutting prompt detail to shrink the prefix.** You asked for thorough prompts. A static prefix is cached, so its marginal cost after the first call is low.
- **Abbreviated JSON keys in tool results.** This saves a few tokens but hurts model accuracy and auditability.

# Backend routes (Problem 7)

`backend/main.py`, run from `backend/` with `../.venv/bin/uvicorn main:app --reload --port 8000`. Shop reads and writes go through the MCP server; `/reset` is the only direct file operation.

- `GET /tickets`: every ticket with raw status, `open`/`resolved` state, and owner.
- `GET /tickets/{ticket_id}`: one ticket in full: notes, owner, recent messages, approvals, POs, latest reply draft.
- `POST /tickets/{ticket_id}/resolve` with `{decided_by, note}`: a human marks a ticket resolved (human-only MCP `resolve_ticket`).
- `POST /tickets/{ticket_id}/direct` with `{decided_by, note}`: a human gives the team a decision or instruction (human-only MCP `add_human_direction`). It is appended to the notes as `DIRECTION:` and sent to boss's inbox; boss acts on it at the next run.
- `POST /tickets/{ticket_id}/run`: start the agent team (boss first) on one ticket in the background. Returns a `run_id` (the audit trail's `root_run_id`). Returns 409 if that ticket is already running.
- `GET /runs` and `GET /runs/{run_id}`: status and final `AgentReport` of runs started since the server began.
- `GET /activity?limit=&ticket_id=&run_id=`: most recent audit-trail events (agent steps, tool calls, delegations, human actions), newest first.
- `GET /approvals?status=pending`: payment, purchase-order, and discount requests awaiting a human.
- `POST /approvals/{approval_id}/approve` with `{decided_by, note}`: a human approves. A payment executes via `decide_approval` (cash rechecked, refused if short); a purchase order is placed (vendor standing and cash rechecked; ETA from today); a discount is recorded.
- `POST /approvals/{approval_id}/reject` with `{decided_by, note}`: a human rejects a pending request.
- `GET /cash`: current checking balance from `cash_accounts`, with the shop date.
- `POST /reset`: restore `campus_customs_new.db` from the original `campus_customs.db`. Returns 409 during a run. The audit trail is kept, and a reset marker is appended.


# Dashboard (Problem 8)

`frontend/` is React + Vite + TypeScript. Run it with `npm run dev`, which serves http://localhost:5173; it calls the API at http://localhost:8000, and CORS allows the Vite origin. The full design rationale is in `output/design.md`.

- **The Docket (left):** all tickets with Roman and Arabic numbers, open/resolved state, detailed status, and owner. "Begin a Fresh Term" calls `/reset` behind a confirmation. `?ticket=<id>` deep-links to a ticket.
- **The Chamber (center):**
  - **Convene the Fellows** (`POST /tickets/{id}/run`).
  - **Five fellow cards,** each showing what that agent **says** and is **doing** (current tool and result digest), its status, and its tool and delegation counts.
  - **Verdict banner** when a run ends: resolved, or parked with the human decisions needed plus *Mark resolved*.
  - **Direction from the Desk** input.
  - **Minutes:** each agent's report summary, actions, and needs-human items.
  - **The Proceedings:** the audit trail as a feed, indented by delegation depth.
  - **The Record:** notes, POs, and the reply draft as a letter.

  During a live run the chamber focuses on that run; otherwise it shows every session on the ticket.
- **Awaiting Assent (right):** pending payment, purchase, and discount approvals. Each shows the amount and, for payments, checking after the payment. Approve and Reject are disabled until the "Signed by" name is set, and each takes a two-step confirm. Recent decisions are listed below as the Acta.
- **Masthead:** shop date (with its Latin rendering) and the checking balance. The balance animates and shows the delta when a payment lands, e.g. "−$840.00 just now".
- **Polling:** 1.5 s for the active run, 2–5 s for everything else. All data comes from the routes above.

# Verified in the live runs (Problem 9)

All three tickets were run through the dashboard against the reset database: 7 team sessions, 92 model requests, 9 delegations, 82.6% of input tokens served from cache.

- **No agent paid or placed anything.** Payments 1 ($840) and 2 ($2,400) and PO 1 ($8) exist only because a human approved approvals 1–3 on the dashboard (`decided_by = Shane Haynes`).
- **Honesty under pressure.** Accounting refused to file a discount approval with an invented percentage and asked boss instead. Customer drafts never mentioned the vendor, invoice, or cash, and never promised a date earlier than the tool's ETA.
- **Minimal teams.** Facilities was never called. Ticket 102 used one delegation, and its closing session used none.
- **Gaps found, with fixes:**
  - The October rent risk went unflagged, because the 30-day cash horizon is too short.
  - Boss gave no discount recommendation, so no discount approval was filed.
  - Ownership churned on 101.
  - The dashboard had no channel for human direction. Added during the run.
