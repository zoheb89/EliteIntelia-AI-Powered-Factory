# EliteInteliA Intelligence Factory — Backend Integration Fix

## Files changed
- `backend/api_server.py`
- `frontend/lib/api.ts`
- `frontend/.env.example`
- `render.yaml`
- `backend/tests/test_api_contract.py`

## Deploy order
1. Replace the Render backend source with this package and deploy the `backend/` service.
2. Ensure Render has:
   - `CORS_ORIGINS=https://eliteintelia-intelligence-factory.vercel.app,https://eliteintelia.com,https://www.eliteintelia.com`
   - existing Databricks/Capgemini secrets as required by the application.
3. Verify Render:
   - `GET /health` -> 200
   - `GET /api/engagements` -> 200 with `{ "items": [...] }`
   - `POST /api/intake` multipart/form-data -> 200
4. In Vercel set:
   - `NEXT_PUBLIC_API_BASE_URL=https://eliteintelia-intelligence-factory.onrender.com`
5. Redeploy Vercel after the frontend change.

Do not add `Content-Type: application/json` to the `/api/intake` request; the frontend intentionally sends `multipart/form-data` with `FormData`.
