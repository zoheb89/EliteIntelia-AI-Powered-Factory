# Provider failover + artifact refresh (v12)

Follow-up to the quota hotfix, driven by what the deployed app actually showed.

## 1. The hotfix is working
Production now shows the correct behaviour:

- the quota message is **no longer stored** as the Discovery artifact
- the banner is red and carries the **provider's own message**:
  *"The AI provider rejected the request: ⚠️ Weekly API call limit exceeded…"*
- the artifact is honestly labelled `deterministic_evidence_only`
- progress reads **2/8**, not an inflated 3/8

## 2. Fixed: artifacts did not appear after a stage ran

Discovery completed and wrote its artifact, but the panel still listed only
*Intake Pack*. `ArtifactViewer` reloaded on `[engagementId, filterKinds]` and
**not on stage completion**, so the list was stale until the user pressed
Refresh — right when they most expect to see the new output.

The workspace now bumps a `refreshKey` when an execution reaches a terminal
state, and the viewer reloads itself.

## 3. Added: multi-provider failover for the legacy path

The root operational problem is that the legacy call path talks to **exactly one
provider**. When its quota is exhausted, every stage degrades until the window
resets — which is what you are living with until 2026-08-30.

`GatewayBackedLLM` exposes the legacy `invoke` / `invoke_json` interface but
routes through the v2 `LLMGateway`, so several providers can be declared and
failover is automatic.

**It is opt-in and non-breaking.** With `LLM_PROVIDERS` unset, the original
client is used and behaviour is unchanged.

```bash
LLM_PROVIDERS=primary:openai_compatible,backup:anthropic

LLM_PRIMARY_ENDPOINT=https://your-gateway/v1/chat/completions
LLM_PRIMARY_API_KEY=...
LLM_PRIMARY_MODEL=...

LLM_BACKUP_API_KEY=...
LLM_BACKUP_MODEL=...

LLM_DEFAULT_PROVIDER=primary
```

Supported kinds: `openai_compatible` (OpenAI, Azure OpenAI, vLLM, Ollama, most
private gateways), `anthropic`, `google`, `bedrock`.

Verified: with the primary exhausted, the backup returned real discovery
output. With every provider exhausted, the quota error surfaces properly rather
than being swallowed. Unparseable output still raises rather than returning a
placeholder, so the poisoning defect cannot reappear through the new path.

## Verification
**279 tests passing** (5 new failover tests) · TypeScript clean · build clean.

## What to do
1. **Deploy this.** The artifact-refresh fix and failover are both live-safe.
2. **Add a backup provider** on Render using the variables above. That unblocks
   you today rather than on 2026-08-30.
3. **Re-run KSC Discovery** once a working provider is configured — the current
   artifact is the deterministic fallback, not AI analysis.

## A note on what you are seeing
The KSC intake is a long, well-written business brief pasted as text, with
`Documents: 0`. The deterministic fallback can only report what it directly
observes, so it produced very little from it. With a working provider that same
intent should yield a full discovery record — the intake content is not the
problem.
