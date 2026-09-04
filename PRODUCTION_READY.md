# EliteInteliA — AI Data Engineering Intelligence Factory
## Production-ready build (Vercel + Render)

One platform for the whole delivery organisation: IT consultants, product owners,
business stakeholders, business analysts, solution architects, data engineers,
platform engineers, Data/AI engineers, DevOps, project & delivery managers,
QA/automation engineers, BI developers and analytics teams.

---

## What was broken, and what changed

The backend was already strong (23 services, 19 endpoints, async execution engine
with persisted traces). The frontend threw most of it away. Fixed:

| # | Problem | Fix |
|---|---------|-----|
| 1 | **9 of 13 routes rendered one identical generic page** — architecture, engineering, AI/analytics, validation, deploy, monitoring, knowledge, settings all looked the same. | `lib/workspaces.ts` metadata now drives each workspace: real pipelines, upstream gating, artifact kinds and persona owners. |
| 2 | **Generated deliverables were invisible.** `/artifacts` and `/artifacts/{kind}` were never called, so nothing the factory produced could be seen. | New `ArtifactViewer` + API clients. Every stage lists, inspects, copies and downloads its artifacts. |
| 3 | **No global engagement context.** Each page read `localStorage` alone; a workspace opened without `?engagement=` was a dead end. | `EngagementProvider` + top-bar engagement switcher. Selection follows you everywhere and auto-selects the latest engagement. |
| 4 | **No role-based experience.** | Persona switcher with 15 roles; the sidebar marks the workspaces each role owns, and each workspace shows its owners. |
| 5 | **Discovery hard-failed without an LLM**, blocking the entire lifecycle at stage 1. | Deterministic evidence-only fallback (reuses the existing universal-intake analyzer), matching the pattern already used by environment/metadata stages. |
| 6 | **Degraded output could look like real AI output.** | Explicit amber "AI enrichment unavailable" banner; artifacts carry `generation_mode: deterministic_evidence_only`. |
| 7 | **`render.yaml` set `CINVENT_DB_PATH=/var/data/…` but declared no disk** — every engagement, artifact and execution was lost on each deploy/restart. | Declared a 1 GB persistent disk mounted at `/var/data`. |
| 8 | Monitoring / Knowledge / Settings were placeholder text. | Real ops console (live execution telemetry, run health), portfolio artifact index, and live API diagnostics + platform catalog. |
| 9 | Backend connectivity failures were silent. | "API live / offline" indicator polls `/health` every 30s. |

### Verified
- `tsc --noEmit` → clean
- `npm run build` → 16/16 routes
- `pytest backend/tests tests` → **46 passed**
- End-to-end in browser: intake → discovery execution → artifacts rendered → architecture unlocked

---

## Deploy

### 1. Backend → Render

Render reads `render.yaml` at the repo root.

1. New → **Blueprint** → connect this repo → Apply.
2. Set env vars on the service:

| Variable | Value |
|---|---|
| `CORS_ORIGINS` | `https://<your-app>.vercel.app` (exact origin, no trailing slash) |
| `CAPGEMINI_LLM_BASE_URL` | your gateway URL |
| `CAPGEMINI_LLM_API_KEY` | your key |
| `CAPGEMINI_LLM_MODEL` | e.g. `openai.gpt-5.1` |
| `DATABRICKS_HOST` / `DATABRICKS_TOKEN` | optional, for platform verification |
| `CINVENT_DB_PATH` | `/var/data/cinvent.db` (already set) |

> **The persistent disk is required.** Without it all data is wiped on every deploy.
> Disks need a paid instance type. On the free tier, delete the `disk:` block and set
> `CINVENT_DB_PATH=data/cinvent.db` — accepting that data does not survive restarts.

Verify: `curl https://<service>.onrender.com/health`

### 2. Frontend → Vercel

1. New Project → import the repo → **Root Directory: `frontend`**.
2. Environment variable:
   `NEXT_PUBLIC_API_BASE_URL = https://<service>.onrender.com`
3. Deploy.

> This variable is inlined at **build** time — after changing it you must **redeploy**,
> not just restart. Settings → API connectivity shows the URL actually in use.

### 3. Connect them
Add the Vercel URL to `CORS_ORIGINS` on Render and redeploy the backend.
The header shows **API live** when wired correctly.

---

## Run locally

```bash
# backend
cd backend
python3.13 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn api_server:app --reload --port 8000

# frontend
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000" > .env.local
npm run dev
```

---

## Lifecycle & governance

`Intake → Discovery → Environment Assessment → Current-State Assessment →
Solution Blueprint → Platform → Metadata → Engineering → QA → BI → Deploy`

- Every stage consumes persisted upstream evidence and emits a governed artifact.
- Downstream stages are **gated**: the UI blocks a run and names the missing upstream
  stage or the required approval.
- The Solution Blueprint needs **explicit human approval** before metadata/engineering.
- Executions run off the HTTP event loop and stream a persisted trace.
- Credentials are stored as **secret reference names only**, never raw values.

## Roles
IT Consultant · Product Owner · Business Stakeholder · Business Analyst ·
Solution Architect · Data Engineer · Platform Engineer · Data/AI Engineer ·
DevOps · QA/Automation · BI Developer · Analytics · Project Manager · Delivery Manager

Switch persona in the top bar; the sidebar highlights that role's workspaces.

## Recommended next steps
1. Add authentication (SSO/OIDC) — there is currently no auth layer.
2. Move SQLite → managed Postgres for multi-instance scaling.
3. Add per-engagement RBAC so roles are enforced, not just presentational.
