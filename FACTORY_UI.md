# Delivery Factory UI (Increment 4)

The backend had run three increments ahead of the frontend — agents, platform
scoring, estimation and the SOW were reachable only through `/api/v2`. This
increment surfaces them.

**217 backend tests passing · TypeScript clean · production build clean.**

---

## Four new screens

### `/factory` — Delivery Lifecycle
All 20 stages, grouped as the spec's navigation (§75). Each card shows:

- **status** (complete / ready / blocked) and **who handles it** — `AGENT`,
  `ENGINE` or `DATA`, so it is obvious which stages are AI work and which are
  deterministic
- **why it is blocked**, in words: *"Evidence must be complete first."*
- **Run**, which dispatches the stage as a background job and streams the live
  trace (gate → execute), then refreshes the board
- **Approve** at the governed gates, styled distinctly because it is a human
  control decision, not a normal action

Below the board, the canonical model is listed with a **provenance badge on
every statement** — colour-coded across CUSTOMER / FACT / AI / RECOMMENDED /
ASSUMED / UNKNOWN. Open questions are counted in amber, because an unanswered
question is a delivery risk, not a neutral fact.

### `/factory/platform` — Platform Selection
Built to be *challengeable*. "How this was decided" shows the method, how many
criteria came from evidence (`5/13`), the detected cloud direction, and the
decision status.

Each criterion shows its weight **and the customer's own words that produced
it**. Criteria nobody mentioned are dimmed and labelled *"Baseline weight — not
mentioned in the evidence"*, so assumption is visually distinct from evidence.

Options A/B/C carry fit, gap-to-leader, advantages, disadvantages, complexity
and reasoning. Selecting a non-recommended option is a first-class action with a
rationale box — the platform advises, the customer decides.

### `/factory/estimate` — Effort & Automation
Every input is exposed and adjustable (entities, reports, sources, team size,
contingency and five complexity multipliers), because a deterministic estimate
should be arguable on its inputs. Shows manual baseline vs delivered effort,
automation saving, duration, effort by role, the critical path, and a work-item
table with the manual / engineering / review split.

Verified: **385.9d manual → 218.6d delivered, 50.7% automation saving.**

### `/factory/sow` — Statement of Work
Leads with issuability, because the product's position is that an incomplete SOW
must not go out. Renders **DRAFT — not issuable** with the incomplete sections
chipped out, the blocking questions listed, and gap sections visually marked —
rather than hiding gaps behind plausible prose.

---

## Design decisions

**A separate API client and context.** `lib/factory-api.ts` and
`FactoryProvider` are deliberately separate from the existing engagement code.
The v2 core models *projects* with a provenance-tagged canonical model; the
original API models *engagements*. Merging them would blur which guarantees
apply to which data.

**Provenance is visual, not textual.** A reader should be able to see at a
glance how much of a screen rests on evidence versus inference. That is the
whole point of §8, and it only works if it is impossible to miss.

**Blockers explain themselves.** A disabled button with no reason is a dead end;
every blocked stage states what must happen first.

## Verified in the browser
Created a project through the UI → attached evidence → ran Discovery and watched
the live job trace → approved the requirements gate → viewed the platform
decision with its criteria breakdown → calculated the estimate → opened the
DRAFT SOW. Progress advanced 1/20 → 14/20 with gates firing correctly.

## Still not built
Domain packs (§53) · customer portal (§51-52) · platform adapters (§16) ·
vector search · delivery digital twin (§56) · PDF/DOCX generation (§29) ·
auth migration onto the new tenant tables · evidence upload through the factory
UI (evidence is currently attached via the API).
