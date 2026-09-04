# C INVENT — Platform Decision + Full Agent Coverage (Increment 3)

**217 tests passing.** Every one of the 20 lifecycle stages now has a handler,
and the complete lifecycle has been driven end-to-end through the live API.

---

## Platform decision engine — §14

The spec is explicit that the decision must **not** start from a named product:

> requirements → constraints → data characteristics → workloads → security
> → cost → skills → latency → governance → platform evaluation

So the scoring is **deterministic**, not model-generated. A recommendation that
changes between runs cannot be defended to a customer.

**How it works.** Criteria weights are derived from the customer's own
requirement text — 14 signal patterns map phrases like *"HIPAA"*, *"near-real-time"*,
*"sub-second latency"*, *"medallion"* onto weighted criteria. Those weights are
applied to a capability catalogue of 7 platforms. Cloud misalignment is a real
penalty, not a tiebreaker.

**Proof it genuinely evaluates** — same engine, different evidence:

| Requirements | Recommended |
|---|---|
| Azure lakehouse, medallion, HIPAA, streaming | **Databricks** (86.2%) |
| Operational app, sub-second latency, on-prem, cost-sensitive | **Azure SQL / PostgreSQL** (74.1%) |
| Google Cloud analytics + warehouse | **BigQuery** |

Tests assert these produce *different* winners, that the result is byte-identical
across runs, and that a criterion nobody mentioned is flagged as
assumption-based rather than quietly weighted.

Output is Option A/B/C with advantages, disadvantages, implementation and
migration complexity, and reasoning that names the decision drivers. Status is
always `RECOMMENDED_PENDING_APPROVAL` — never a commitment.

**Humans can override.** `POST /platform/decision` records a different choice
with its rationale and marks `followed_recommendation: false`. The platform
advises; the customer decides.

### The agent is a deliberate hybrid
`PlatformSelectionAgent` scores deterministically, then uses the model **only to
narrate**. A test feeds the model output *"Use Amazon Redshift instead"* and
asserts the ranking is unchanged. When the provider is down, scoring is
unaffected — only the prose is lost.

## Agent coverage — 20/20 stages

| Handler | Stages |
|---|---|
| **Agent** (15) | discovery, questions, assessment, requirements, platform, architecture, data, ai, bi, application, governance, engineering, testing, deployment, operations |
| **Engine** (3) | estimation, sow, commercial — deterministic, so they are reproducible |
| **Data** (2) | intent, evidence — satisfied by what the customer supplies |

New agents: `QuestionSetAgent` (§11), `PlatformSelectionAgent` (§14),
`ArchitectureAgent` (§15), and design agents for data, AI, BI, application,
governance, engineering, QA, operations and handover (§17–§22).

### Fallbacks ask, they never invent
Every design agent's degraded path emits **a checklist of what must be
established with the customer**, with all content sections empty. A test asserts
this for all nine agents: a fabricated data model or governance control is worse
than an admitted gap (§68).

## Verified end-to-end

All 18 executable stages driven through the live API:

```
discovery COMPLETED    platform COMPLETED     estimation engine
questions COMPLETED    architecture COMPLETED sow        engine
assessment COMPLETED   data/ai/bi/application commercial engine
requirements COMPLETED governance/engineering testing/deployment/operations COMPLETED
------------------------------------------------------------------
FINAL: {'complete': 20, 'total': 20}   artifacts: 22   incomplete: NONE
```

Human approval gates fire correctly at requirements, platform, architecture,
sow, commercial and deployment.

## Two defects found by the walkthrough

Both were **stages that could never complete**, silently:

1. **`questions` declared `question_set`** but the discovery agent emitted
   `discovery`. The stage was permanently incomplete. Fixed by adding
   `QuestionSetAgent`, which is valuable in its own right — it converts each
   UNKNOWN into a specific question with answer options and an owning role.
2. **`commercial` declared `commercial`** but the SOW endpoint only saved `sow`,
   so **the deployment gate could never open**. The commercial stage now emits
   its own artifact (as does `automation_assessment` for estimation).

A regression test (`test_every_declared_artifact_is_actually_produced`) now
walks all 20 stages and fails if any declares an artifact nothing emits.

## New API

| Endpoint | Purpose |
|---|---|
| `GET /api/v2/agents` | Per-stage handler map and coverage |
| `GET /api/v2/projects/{id}/platform/options` | Scored options with breakdown |
| `POST /api/v2/projects/{id}/platform/decision` | Record the human decision |

## Still not built
Domain packs (§53) · customer portal (§51-52) · platform adapters (§16) ·
vector search · delivery digital twin (§56) · PDF/DOCX generation (§29) ·
auth migration onto the new tenant tables · frontend surfacing of agents,
estimates, platform options and the SOW.
