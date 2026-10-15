# Dashboard design: "The Desk"

`frontend/`: React 19 + Vite + TypeScript. It talks to the FastAPI backend at `http://localhost:8000` (override with `VITE_API_BASE`). Start it with `npm run dev`, which serves http://localhost:5173.

## The idea
A human-oversight console that looks like the office of a Yale residential college. The five agents are the college's **fellows**, the tickets are the **docket**, the audit trail is **the proceedings**, and approvals wait for your **assent**.

The Yale theme is deliberately overdone, but it is layered on top of a conventional, legible operations layout. Every flourish sits next to a plain label, so it never costs clarity.

## Aesthetic choices
| Choice | What | Why |
|---|---|---|
| Palette | Yale Blue `#00356B` (masthead, primary actions, active states), parchment and paper backgrounds, limestone borders, brass hairlines. Ivy green means resolved or done; oxblood means payments, refusals, errors. | Yale Blue carries identity and every "act now" signal. The status colors map to meaning, and every status also has a text label, so color is never the only cue. |
| Type | Cormorant Garamond (display, small caps), EB Garamond (body, tabular lining numerals), IBM Plex Mono (tool names, ids). | Old-style serifs read as collegiate print. Tabular figures keep dollar amounts aligned. Monospace marks machine output, such as tool calls, so you can tell the agents' words from their actions at a glance. |
| Masthead | Deep-blue band, a faint repeating Gothic-tracery pattern, a double brass rule, an original shield crest ("CC" over an open ledger), and a motto ribbon. | It sets the tone in one glance and holds the two things you check most: the shop date and checking. |
| Gothic lancet arches | Each fellow's card is capped with a pointed arch and a wax-seal monogram. The arch keeps its proportions at any width. Arches stay grey and the card dims while that fellow is not summoned. | The architecture of Sterling and the residential colleges, used as information: you can see who was involved without reading anything. |
| Laid-paper background | Faint horizontal rules, like a bursar's ledger. | Texture without noise. |

## The overdone part, on purpose
- **Fellows' titles:** Head of College (Boss), Keeper of the Stores (Inventory), The Bursar (Accounting), Superintendent of Grounds (Facilities), Dean of Patrons (Customer Service). The plain agent name sits beneath each title.
- **Roman numerals:** tickets are CI, CII, CIII, with "No. 101" beside them. The shop date is also rendered in Latin, e.g. *Die XXXI Augusti MMXXVI*.
- **Latin motto:** *Lux et Inventarium*, light and an accurate count.
- **The voice of the controls:** the run button reads "Convene the Fellows". Reset is "Begin a Fresh Term". Decided approvals are the "Acta". The customer reply draft is shown as a letter on shop letterhead.
- **Celebration:** a resolved ticket earns a "Boola Boola!". The colophon nods to the old alma-mater line: "For the Desk, for the Shop, and for Yale".

## Layout and why
Three columns that follow the work from left to right: **choose → watch → decide**.

1. **The Docket (left):** all tickets as cards showing the Roman and Arabic number, subject, requester, an open/resolved chip, the detailed status, the owner, and an "In session" chip during a run. Selecting a card drives everything else. "Begin a Fresh Term" (reset) sits here, behind an inline confirmation that spells out exactly what gets undone.
2. **The Chamber (center):**
   - **Ticket header** with a single primary action, *Convene the Fellows* (`POST /tickets/{id}/run`). It is disabled while a run is live or the ticket is resolved.
   - **Verdict banner** when the run ends:
     - **Resolved:** "Boola Boola!" plus the boss's summary.
     - **Parked**, e.g. waiting on a human: the summary, the decisions the human must make, and a *Mark resolved* control that requires your name and a note.
     - **Failed:** the error.
   - **Five fellow cards.** Each shows status (Not summoned / Deliberating / At work / Reported / Faltered), what the agent **says** (its latest words, as a quote) and what it is **doing** (current tool or delegation, plus a one-line digest of the result), and counts of tool calls and delegations. Live cards pulse.
   - **Minutes of the Meeting:** one short summary per agent from its filed report, with actions taken and anything that requires the Desk.
   - **The Proceedings:** the full activity feed from `/activity`, chronological and indented by delegation depth, so the boss → specialist tree is visible. A toggle hides tool calls when you only want the conversation.
   - **The Record:** ticket notes, purchase orders, and the reply draft as a letter, labeled "draft, not sent".
3. **Awaiting Assent (right):** pending payments, purchase orders and discounts. Each card shows:
   - the amount, large;
   - what the request is;
   - which fellow asked, and a link to its ticket;
   - for payments, **checking after payment**, turning oxblood if cash is short. Purchase orders state that they commit spend but don't debit cash today.

   Below the cards, the Acta lists recent decisions.

## Usability principles applied
- **One primary action per area,** in Yale Blue. Secondary actions are outlined; destructive ones are oxblood.
- **Approvals need a signature.** Approve and Reject stay disabled until you enter a name in the masthead's "Signed by" field (stored locally). That name is sent as `decided_by`, so every approval in the audit trail is attributable.
- **Two-step confirm on irreversible actions.** Approving a payment shows "Pay $840.00 now, signed … This cannot be undone." The same applies to rejecting and to resetting.
- **Feedback for every change:**
  - The balance in the masthead animates and shows the delta (e.g. "−$840.00 just now") when a payment lands. This is the "checking drops after an approved pay" requirement, made visible.
  - Toasts confirm each action.
  - When a run finishes, everything refreshes immediately, so the ticket's new state shows without a reload.
- **Live, but calm.** Runs poll at 1.5 s for the active ticket; everything else polls every 3–5 s. The feed auto-scrolls only while a run is live.
- **Truthful states.** The dashboard never fakes a resolution. A run that parks a ticket shows "parked", and resolution is either the agents' outcome or an explicit, signed human action (`POST /tickets/{id}/resolve`).
- **Failure is visible.** If the backend is unreachable, a banner says so and gives the start command. API errors, such as a refused payment, appear as oxblood toasts with the server's reason.
- **Accessibility and responsiveness:**
  - focus rings on every control;
  - `aria-live` regions for the feed, balance and toasts;
  - text on every status;
  - reduced-motion support;
  - the layout collapses to two columns, then one, on narrower screens.

## What makes it special
It turns an audit log into a meeting you can watch: who was summoned, what each fellow said, what each one did, and what it filed. That is wrapped in a confident, slightly theatrical Yale identity, and every flourish is tied to a working signal. The arches show who was involved. The Roman numerals sit beside Arabic ones. The Latin date sits under the real one. The ledger's balance visibly falls the moment you sign a payment.
