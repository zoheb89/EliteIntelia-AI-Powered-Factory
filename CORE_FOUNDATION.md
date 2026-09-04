# C INVENT — Core Foundation (Increment 1)

Against the master specification. This increment builds the layer the spec says
to build first:

> *"Start with the canonical project model, persistence, LLM gateway, evidence
> system, lifecycle engine, agent orchestration and artifact factory before
> adding platform execution."*

**Scope honesty:** §1–76 is a multi-quarter product. This is the foundation, not
the finished product. What is real, partial and not started is listed below.

---

## Built and tested (143 tests passing)

### Canonical model + provenance — §8, §68
`core/domain/provenance.py`

Six provenance levels: `CUSTOMER_DECISION > FACT > AI_INFERENCE > RECOMMENDATION
> ASSUMPTION > UNKNOWN`.

The no-hallucination rule is **structurally enforced, not documented**:
- a claim of `FACT` with no `EvidenceRef` is automatically downgraded to
  `AI_INFERENCE` / `LOW` confidence with a note explaining why
- enforced in the domain object *and* at the API boundary
- `reconcile()` means a later AI run can never overwrite a `CUSTOMER_DECISION`

### Delivery lifecycle — §2, §75
`core/domain/lifecycle.py`

20 stages across 11 navigation groups, from Business Intent to Operations &
Handover. The lifecycle is **data, not branching logic** — `requires` encodes the
gates, so `next_stage()`, `blockers()` and `downstream_of()` are derived. A test
asserts the dependency graph is acyclic and correctly ordered.

Approval gates (`HUMAN`, `CUSTOMER`) block downstream stages until recorded.

### LLM Gateway — §1, §35
`llm/gateway/`, `llm/providers/`

**Vendor-neutral, with no vendor assumed or defaulted.** Adapters ship for
OpenAI-compatible (covers OpenAI, Azure OpenAI, vLLM, Ollama, private gateways),
Anthropic, Google and AWS Bedrock, plus a deterministic `echo` provider for
offline tests.

- retries with exponential backoff on retryable errors only
- automatic **fallback to the next provider** when one fails
- `complete_json()` parses JSON, then a fenced block, then asks the model to
  repair its own output — and **raises rather than returning a guess**
- API keys are redacted in every describe/log path (asserted by test)
- configured entirely from env; adding a provider needs no core change

### Persistence — §40, §58, §64, §65
`persistence/`

16 tables, SQLAlchemy 2.x, **runs on SQLite and PostgreSQL** (`DATABASE_URL`).

- **Tenant isolation is structural**: a `Repository` is constructed *for* a
  tenant and writes every filter itself, so callers cannot forget it.
  Cross-tenant access raises `TenantScopeError` rather than returning `None`.
- **Versioning**: artifacts insert a new version and mark the previous one
  `superseded_by`. Approved content is never overwritten.
- Every artifact pins the `project_version` it was generated from.
- **Delivery graph** (`TraceLink`) answers *"why does this exist?"* by walking
  edges upstream to the originating requirement.
- Append-only `AuditEvent` with actor, action, before/after and reason.

### Job engine — §42, §43, §44
`jobs/engine.py`

Directly addresses the 504 timeouts in the POC. Jobs are **step sequences with
checkpointed output**:

- statuses `QUEUED / RUNNING / COMPLETED / FAILED / RETRYING / CANCELLED / PARTIAL`
- a mid-sequence failure yields `PARTIAL` — **completed work is preserved**
- `resume()` skips completed steps (asserted: a completed step does not re-run)
- per-step retries with backoff; optional steps degrade instead of failing
- `submit()` runs in the background and returns immediately

### Core API — §63
`core/api_v2.py`, mounted at `/api/v2` **alongside the existing routes**, so the
deployed Vercel + Render application keeps working unchanged.

`/lifecycle` · `/projects` · `/projects/{id}/lifecycle` · `/statements` ·
`/unknowns` · `/artifacts` · `/approvals` · `/impact/{stage}` · `/audit` ·
`/llm/providers` · `/llm/complete` · `/jobs/{id}`

---

## Partial

| Area | State |
|---|---|
| Change Impact (§31) | Stage-level downstream impact is live. Requirement-level cascade needs the agents. |
| Evidence (§8) | Schema, chunking, hashing and classification fields exist; RFI/RFP/RFQ classification still runs in the older `universal_intake` service. |
| Auth (§57) | Working PBKDF2 + RBAC from the previous increment; not yet migrated onto the new `users_v2`/tenant tables. |
| Artifacts (§28) | Versioned storage is real; PDF/DOCX/PPTX generation (§29) is not wired to the new factory. |

## Not started
Agent orchestrator (§36) · Tool system (§37) · Estimation (§25) · SOW (§26) ·
Commercial (§27) · Application factory (§20) · Domain packs (§53) ·
Customer portal (§51/§52) · Platform adapters (§16) · Vector search (§40) ·
Delivery digital twin (§56)

---

## Configuration

```bash
# Database — SQLite for dev, Postgres for production. No code change.
DATABASE_URL=postgresql://user:pass@host/db

# LLM providers. No vendor is assumed; declare what you have.
LLM_PROVIDERS=primary:openai_compatible,backup:anthropic
LLM_PRIMARY_ENDPOINT=https://your-gateway/v1/chat/completions
LLM_PRIMARY_API_KEY=...
LLM_PRIMARY_MODEL=your-model
LLM_BACKUP_API_KEY=...
LLM_BACKUP_MODEL=your-model
LLM_DEFAULT_PROVIDER=primary
```

Single-provider deployments may instead set `LLM_ENDPOINT` / `LLM_API_KEY` /
`LLM_MODEL`. With nothing configured the gateway reports "not configured"
rather than defaulting to any vendor.

## Verification
```bash
cd backend && python -m pytest tests -q     # 143 passed
```

Two defects were found by these tests and fixed:
1. `FACT` provenance was enforced in the domain object but bypassed by the API —
   AI-generated content could enter as fact without evidence.
2. Audit events were written with an empty `project_id`, orphaning them from the
   project, so the §59 audit trail read as empty.
