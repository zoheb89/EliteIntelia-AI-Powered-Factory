# EliteInteliA Intelligence Factory — Build 0.1.25

## Purpose

This build fixes the lifecycle execution UX and removes the black-box `Running...` behavior.

### Fixed

1. **Architecture runs asynchronously** and returns an execution ID immediately.
2. **Persisted execution telemetry** is stored in SQLite in a dedicated `executions` table.
3. **Architecture pipeline is observable:**
   - Environment Assessment
   - Current-State Assessment
   - Solution Blueprint
4. **Current-State Assessment is rendered as a persisted evidence panel** after execution.
5. **Engineering is a controlled two-step pipeline:**
   - Engineering Metadata
   - Data Engineering
6. **Engineering automatically generates metadata after Blueprint approval** before engineering generation.
7. Lifecycle gates remain enforced; the system does not fake customer platform verification.
8. **Platform & Environment workspace added** so the user has an explicit path to select and verify the target platform.
9. **Execution trace endpoint added** for auditability and troubleshooting.
10. Long-running stage work is moved out of the HTTP event loop using FastAPI BackgroundTasks.
11. Existing lifecycle tests pass.

## Deployment

### Render API

Root directory:

`backend`

Build:

`pip install -r requirements.txt`

Start:

`uvicorn api_server:app --host 0.0.0.0 --port $PORT`

The Render environment must contain the existing LLM / Databricks variables used by the application.

### Vercel frontend

Set:

`NEXT_PUBLIC_API_BASE_URL=https://<your-render-api-host>`

Then deploy the `frontend` directory with the existing Next.js configuration.

## Expected user flow

`Intake → Discovery → Architecture → Blueprint Approval → Platform & Environment → Engineering → AI & Analytics → Validation → Deploy`

Architecture is no longer a single blocking HTTP call. The UI receives an execution ID and polls `/api/engagements/{id}/executions/{execution_id}` until completion.

## Production-style guardrail

A customer platform is never treated as verified merely because the C INVENT control-plane connector exists. Engineering requires a verified customer target platform. Synthetic validation remains a separate deterministic validation capability.
