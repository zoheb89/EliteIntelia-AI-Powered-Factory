# EliteInteliA Intelligence Factory — Lifecycle Fix 1.0.2

## Fixes

1. **Discovery → Architecture lifecycle is now correct.**
   - Successful Blueprint generation marks `architecture` complete.
   - Blueprint approval remains a governance gate for downstream metadata/engineering; it no longer makes the Architecture stage appear pending.

2. **Architecture Run Stage now executes its prerequisites automatically.**
   - Requires successful Discovery.
   - Refreshes Environment Assessment when missing/stale.
   - Refreshes deterministic Assessment when missing/stale.
   - Runs Solution Blueprint only after those prerequisites succeed.
   - Returns an `execution_trace` so the UI can show what actually ran.

3. **Stage API supports business-facing names.**
   - `discovery`
   - `architecture`
   - `platform`
   - `engineering`
   - `ai`
   - `validation`
   - legacy internal names remain supported.

4. **Validation errors remain JSON-safe.**
   - Multipart/binary validation input no longer causes the `UnicodeDecodeError` seen in Render logs.

5. **Frontend API helper** posts an explicit empty JSON body for lifecycle stage calls and types the execution trace.

## Expected lifecycle after running Discovery

`Intake 1/8 → Discovery 2/8 → Architecture 3/8 → Platform 4/8 ...`

After Architecture is generated, the UI should show:
- Discovery: COMPLETE
- Architecture: COMPLETE
- Platform: PENDING
- Blueprint approval: REQUIRED for downstream engineering/metadata

## Deploy

### Render
Use `render.yaml` or set:
- Root directory: `backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn api_server:app --host 0.0.0.0 --port $PORT`

### Vercel
Replace the existing frontend `lib/api.ts` with the supplied file and redeploy.

Set:
`NEXT_PUBLIC_API_BASE_URL=https://eliteintelia-intelligence-factory.onrender.com`

## Smoke test

1. Create a new engagement with the RFP.
2. Run **Discovery & Assessment**.
3. Confirm lifecycle is `2/8`.
4. Use the **Solution Architecture** workspace and click **Run Stage**.
5. The backend should execute Environment Assessment → Assessment → Blueprint in one controlled request.
6. Confirm lifecycle becomes `3/8` and the Architecture stage is COMPLETE.
7. Approve the Blueprint before attempting Metadata/Data Engineering.

Do not treat a successful synthetic/POC run as customer-environment verification. Platform verification remains a separate gate.
