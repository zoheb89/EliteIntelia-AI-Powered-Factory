# EliteInteliA 1.1.0 — Production Execution Fix

## Included
- Persisted asynchronous stage execution with execution IDs and polling.
- Architecture pipeline: Environment Assessment → Current-State Assessment → Solution Blueprint.
- Engineering pipeline: approved Blueprint → Metadata → Engineering.
- Current-State Assessment is persisted and displayed in the Architecture workspace.
- Live execution heartbeat every 4 seconds while a provider/LLM call is still running. Heartbeats are telemetry only and never fake completion.
- Execution elapsed time and trace-event count exposed to the UI.
- Stale queued/running executions are recovered after 30 minutes so a Render/container restart cannot permanently block a stage.
- Configurable SQLite path through `CINVENT_DB_PATH`; Render manifest points to `/var/data/cinvent.db` for use with a persistent disk.
- FastAPI/uvicorn production dependency set included.
- Existing lifecycle gates and blueprint approval remain enforced.

## Validation
- Backend test suite: 46 passed.
- FastAPI `/health` smoke test: 200 OK.
- Frontend dependency installation/build was not completed in the sandbox because `npm install` exceeded the execution timeout; the frontend source is included in full.

## Render
- Root directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn api_server:app --host 0.0.0.0 --port $PORT`
- Set `CORS_ORIGINS` to the deployed Vercel origin.
- For persistent engagement state, attach a Render persistent disk mounted at `/var/data`.

## Vercel
Set `NEXT_PUBLIC_API_BASE_URL` to the Render backend URL.
