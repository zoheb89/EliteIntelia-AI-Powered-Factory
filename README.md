# EliteInteliA Intelligence Factory — GitHub Ready

This repository contains the cloud-first product:

- `frontend/` — Next.js / React EliteInteliA UI
- `backend/` — FastAPI + the existing C INVENT Python engine
- `render.yaml` — Render backend deployment
- `backend/Dockerfile` — container deployment
- `backend/config.yaml` — non-secret product configuration

## Cloud architecture

Browser → Vercel/Next.js → FastAPI/Render → C INVENT engine → Databricks/customer platforms

## Deploy backend

1. Push this repository to GitHub.
2. Create a Render Web Service from the repository.
3. Set Root Directory to `backend`.
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `uvicorn api_server:app --host 0.0.0.0 --port $PORT`
6. Add environment variables/secrets:
   - `CORS_ORIGINS`
   - `DATABRICKS_HOST`
   - `DATABRICKS_TOKEN`
   - `DATABRICKS_WAREHOUSE_ID`
   - `CAPGEMINI_LLM_BASE_URL`
   - `CAPGEMINI_LLM_MODEL`
   - `CAPGEMINI_LLM_API_KEY`
   - optional Capgemini workspace settings
   - `CINVENT_ALLOW_MUTATIONS=false` initially
7. Verify `https://<render-host>/health` and `/docs`.

## Deploy frontend

1. Import the same GitHub repository into Vercel.
2. Set Root Directory to `frontend`.
3. Framework: Next.js.
4. Add:
   `NEXT_PUBLIC_API_BASE_URL=https://<your-render-host>`
5. Deploy.

## First test

1. Open the Vercel URL.
2. Create an engagement.
3. Submit business intent or upload an RFI/RFP/PDF/DOCX/XLSX.
4. Confirm intake is created.
5. Run Discovery.
6. Run Environment Assessment.
7. Run Current-State Assessment.
8. Generate Architecture.
9. Approve Architecture.
10. Configure/verify the target platform if required.
11. Generate Metadata.
12. Generate Engineering.
13. Run Validation.
14. Generate/download the PDF and intake evidence pack.

## Important

Do not commit customer credentials, API keys, `.env` files, tokens or secrets.

The MVP keeps SQLite persistence inside the backend container. For enterprise production, move persistence to managed PostgreSQL and evidence/artifacts to object storage before using real customer data at scale.

The backend is intentionally evidence-driven: it must not claim customer source connectivity or platform provisioning without actual verification evidence.
