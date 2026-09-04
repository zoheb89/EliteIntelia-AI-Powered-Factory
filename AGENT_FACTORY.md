# C INVENT — Agent Factory (Increment 2)

Turns the lifecycle from a data structure into a working factory.
**173 tests passing** (30 new).

---

## Agent orchestrator — §36

```
User -> Orchestrator -> Agent -> Tools -> Canonical Model -> Artifacts -> Approval
```

The split is deliberate: **agents propose, the orchestrator commits.**

An agent is a pure function from evidence to an `AgentOutput`. It cannot write
to the database. The orchestrator owns gate checking, persistence, provenance-safe
writes, versioning, the AI-run record and audit — so those guarantees are
implemented once, not per agent (§69).

Adding an agent is one line in the `AGENTS` registry. A test asserts every
registered agent actually owns a lifecycle stage.

**Implemented:** `discovery`, `assessment`, `requirements`.
**Not yet:** the remaining 16 stages return a truthful `501 AGENT_NOT_IMPLEMENTED`
rather than pretending to work.

## Tool system — §37

Agents *look things up* instead of asserting from memory. Nine read-only tools
over the canonical model: `project_summary`, `list_evidence`, `read_evidence`,
`search_evidence` (returns citable excerpts + locators), `list_statements`,
`list_unknowns`, `list_artifacts`, `read_artifact`, `platform_capabilities`.

Read-only by design: writes stay inside the approval path. Every invocation is
recorded — success or failure — and attached to the agent's output, so a
conclusion can be traced to the exact reads that produced it.

## Three guarantees enforced in `BaseAgent`

1. **Provenance on every statement (§8)** — output is normalised through the
   domain `Statement`, so a model claiming `FACT` without a citation is
   automatically downgraded to `AI_INFERENCE`. Tested both ways.
2. **Never block the lifecycle (§44)** — if the provider is down, the agent
   returns a deterministic evidence-only result, explicitly labelled
   `generation_mode: deterministic_evidence_only`. Never dressed up as AI output.
3. **Malformed output degrades, never crashes** — a JSON array where an object
   was expected falls back rather than failing the stage.

## Estimation engine — §23, §24, §25

**Deterministic by design.** An LLM that invents person-days is a commercial
liability; estimates must be reproducible and defensible line by line.

Every work item is classified `FULL_AUTOMATION` / `AI_ASSISTED` /
`HUMAN_DECISION` / `MANUAL`, and **review effort on generated work is never
netted to zero** — AI output still has to be checked.

Worked example (24 requirements, 5 sources, 18 entities, 12 reports):

| | |
|---|---|
| Manual baseline | 358.6 days |
| Delivered (incl. contingency) | **201.3 days** |
| Automation saving | 183.5 days (**51.2%**) |
| Duration | 24.2 weeks, 6 people |
| Critical path | `WI-DISC → WI-REQ → WI-MODEL → WI-PIPE → WI-SEM → WI-RPT` |

Every multiplier used is returned with the total, so a reviewer challenges an
input rather than the number.

## SOW & Commercial factory — §26, §27

All 28 specified sections, assembled **deterministically from the canonical
model** — never model-generated.

The important behaviour: it **refuses to issue an incomplete SOW**. Missing
sections are reported explicitly and the document is stamped
`DRAFT — not issuable` rather than filled with plausible prose (§68).

```
sections 22/28 complete | issuable=False
reason: 6 section(s) incomplete and 0 open question(s) outstanding
```

Commercial output is **pricing inputs only** — the rate card is emitted with
`null` values and the note *"this platform does not set or commit pricing"*.
A test asserts no rate can ever be populated automatically.

## Background execution — §42

Stages run as resumable jobs by default; the request returns immediately with a
`job_id`. Verified trace:

```
running  -        stage:discovery started.
running  gate     Discovery readiness check is running.
success  gate     Discovery readiness check complete.
running  execute  Discovery generation is running.
success  execute  Discovery generation complete.
success  -        stage:discovery completed.
```

---

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/v2/agents` | Implemented agents and unimplemented stages |
| `GET /api/v2/tools` | Tool catalogue |
| `POST /api/v2/projects/{id}/stages/{stage}` | Run a stage (background by default) |
| `POST /api/v2/projects/{id}/estimate` | Deterministic effort + automation |
| `GET /api/v2/projects/{id}/sow?fmt=json\|markdown` | Assemble the SOW |
| `GET /api/v2/jobs/{id}` | Poll job status and trace |

Honest status codes: `409 STAGE_BLOCKED` when a gate fails,
`501 AGENT_NOT_IMPLEMENTED` for stages without an agent.

## A defect found by testing

**The lifecycle could not start.** `intent` and `evidence` had no agent, so the
first two stages were unreachable and every downstream stage stayed blocked.
These are not AI work — `intent` is satisfied when the customer states what they
want to build, `evidence` when a document is attached. The orchestrator now
derives them from data presence. State derivation was also duplicated between
the orchestrator and the API; it is now defined once.

## Still not built
Platform selection, architecture, data/AI/BI/application design and governance
agents · application factory (§20) · domain packs (§53) · customer portal
(§51-52) · platform adapters (§16) · vector search · digital twin (§56) ·
PDF/DOCX generation (§29) · auth migration onto the new tenant tables.
