# Authentication & Pipeline Execution

Two additions that close the last production gaps.

---

## 1. Authentication + RBAC

### Security properties
| Concern | Implementation |
|---|---|
| Password storage | **PBKDF2-HMAC-SHA256**, 240k rounds, unique 16-byte salt per user. No plaintext, ever. |
| Sessions | Signed **HMAC-SHA256** tokens with an expiry claim. Stateless — the API scales horizontally with no shared session store. |
| Missing secret | **Fails closed**: with `AUTH_REQUIRED=true` and no `AUTH_SECRET`, the service refuses to issue tokens rather than signing with a guessable default. |
| User enumeration | Login performs password hashing whether or not the account exists, so response timing does not reveal registered emails. |
| Tampering | Signature verified with `hmac.compare_digest` (constant-time). Forged or edited tokens are rejected. |

### Roles
| Role | Can |
|---|---|
| `viewer` | Read engagements, artifacts, lineage, monitoring |
| `editor` | Everything above **+** run stages, approve gates, save/run pipelines, create intakes |
| `admin` | Everything above **+** manage users and roles |

Guarded endpoints: `POST /api/intake`, `/stages/{stage}`, `/approvals/*`,
`/platform`, `/pipeline`, `/pipeline/run` (editor) and all `/api/auth/users*` (admin).

### Rollout
`AUTH_REQUIRED` defaults to **false**, so existing deployments keep working.
Turn it on when ready:

```bash
AUTH_REQUIRED=true
AUTH_SECRET=$(openssl rand -hex 32)
ADMIN_EMAIL=you@company.com
ADMIN_PASSWORD=<strong password>       # seeds the first admin, then remove
```

The first admin is created only when the user table is empty. **Delete
`ADMIN_PASSWORD` after your first sign-in.**

### Endpoints
`GET /api/auth/config` · `POST /api/auth/login` · `GET /api/auth/me` ·
`GET/POST /api/auth/users` · `PUT /api/auth/users/{email}/role` · `DELETE /api/auth/users/{email}`

---

## 2. Pipeline execution

The Studio now **runs** the pipeline it generates, not just emits code.

### Engines

**`sandbox` (default, no credentials)** — executes the generated SQL against an
in-memory SQLite database seeded with synthetic rows derived from each Source
node's declared columns. Returns per-model row counts, sample rows and dbt test
results. Lets an engineer validate pipeline *logic* before any warehouse exists.

**`databricks`** — submits the same models to the customer's SQL warehouse via
`statement_execution`. Requires `DATABRICKS_HOST`, `DATABRICKS_TOKEN` and
`DATABRICKS_WAREHOUSE_ID`.

Every result is labelled with the engine that produced it, so sandbox output can
never be mistaken for a real warehouse run.

### What you get back
- per-model **status, row count, elapsed ms**
- an **8-row data preview** per model
- **dbt generic tests** (`not_null`, `unique`) executed with failing-row counts
- failures stop the run at the offending model and return its SQL

### A correctness bug worth knowing about
SQLite assigns NUMERIC affinity to any unrecognised type name, so
`cast(order_status as string)` silently returns **integer 0** — which destroyed
every text value and made filters match all rows. The runner now rewrites
warehouse types to real SQLite types (`string`→`TEXT`, `bigint`→`INTEGER`,
`decimal(18,2)`→`REAL`) before executing. Regression test:
`test_sandbox_filter_actually_filters`.

### Endpoints
`POST /api/studio/run` (stateless) · `POST /api/engagements/{id}/pipeline/run`
(persists a `pipeline_run` artifact and an audit entry)

---

## Verified
- **88/88 backend tests pass** (25 new: hashing, tokens, expiry, tampering, RBAC, user store, sandbox execution)
- `tsc --noEmit` clean · production build clean
- In-browser: sign-in gate blocks the app → login unlocks it; RBAC confirmed over HTTP
  (viewer `200` on reads, `403` on mutations and admin routes)
- Studio run: *"3 models, 9/9 tests passed"* with live data preview
