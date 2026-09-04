# EliteInteliA Intelligence Factory — Final Backend Fix

## Root cause fixed

The deployed backend was returning:

`POST /api/engagements/{id}/stages/discovery -> 400 Unsupported stage: discovery`

The `/stages/{stage}` endpoint did not contain a `discovery` action. It only contained internal actions such as `environment_assessment`, `assessment`, `blueprint`, `engineering`, etc.

The fix:

- Adds the business-facing `discovery` stage.
- Makes the discovery request body optional, so the frontend can call the stage with no JSON body.
- Keeps the existing `/api/engagements/{id}/discovery` endpoint intact.
- Adds UI-to-backend aliases:
  - `discovery` -> `run_discovery`
  - `architecture` -> `run_blueprint`
  - `platform` -> `run_environment_assessment`
  - `engineering` -> `run_engineering`
  - `ai` -> `run_bi`
  - `validation` -> `run_poc_validation_pack`
- Retains the existing internal stage names for backward compatibility.
- Adds a safe FastAPI validation-error handler so raw multipart bytes cannot cause the previous `UnicodeDecodeError`.
- Supports both `CORS_ORIGINS` and the currently configured `FRONTEND_ALLOWED_ORIGINS`.
- Bumps the backend version to `1.0.1-cloud`.

## Deployment

Replace the deployed backend `api_server.py` with:

`api_server.py`

Then redeploy the Render backend.

No frontend code change is required for the specific `Unsupported stage: discovery` error.

## Environment variable

Keep:

`FRONTEND_ALLOWED_ORIGINS=https://eliteintelia.com,https://www.eliteintelia.com,https://eliteintelia-intelligence-factory.vercel.app`

The fixed backend now reads this variable when `CORS_ORIGINS` is not present.

## Smoke test

After Render reports the service live:

1. Open the Vercel frontend.
2. Open the existing engagement.
3. Go to Discovery & Assess.
4. Click **Run Stage**.
5. Confirm the Render log shows:
   `POST /api/engagements/{engagement_id}/stages/discovery 200 OK`
6. Confirm the UI changes Discovery from `PENDING` to `COMPLETE`.
7. Confirm no `[object Object]` error is displayed.
8. Then test Architecture.

The earlier `GET /api/engagements 404` and `POST /api/intake 422` messages in the old log were followed by successful `200 OK` responses after redeployment. The remaining demonstrated blocker is the missing `discovery` stage mapping.
