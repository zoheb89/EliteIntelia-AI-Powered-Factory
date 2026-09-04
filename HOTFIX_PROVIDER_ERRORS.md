# Hotfix — provider errors stored as delivery evidence

## What happened in production

The AI gateway returned **HTTP 200** with this in the response body:

> ⚠️ Weekly API call limit exceeded. You used all 100 LLM API calls allowed for
> your tier. Limit will reset on 2026-08-30 23:00 UTC.

That message was **stored as the Discovery artifact**, the stage was marked
**COMPLETE**, and the lifecycle advanced to **3/8** — with Architecture also
"complete" on top of it. A quota error was presented to the customer as
delivered analysis.

This is precisely the failure the provenance design exists to prevent, so it is
worth being exact about how it got through.

## Two defects, compounding

**1. `invoke_json` returned a success-shaped value for a failure.**

```python
except Exception:
    return {"_raw": content, "_repair_raw": repair["content"]}   # looks like a result
```

The caller's guard was `if "error" in out and len(out) == 1`. A `_raw` payload
has no `error` key, so it sailed through and was persisted.

**2. The quota error arrived with a 200 status.** Only `status_code >= 400` was
treated as failure, so a rejection carried in the body was indistinguishable
from a completion.

## The fix — three layers

**Client boundary.** `_reject_provider_error()` inspects the response body for
provider rejections (quota, rate limit, credits, content policy) and raises
`CapgeminiLLMQuotaError`. It only matches responses under 1200 characters, so a
genuine analysis that *discusses* rate limits is not falsely rejected — there is
a test for exactly that.

**Fail, don't placeholder.** `invoke_json` now raises `CapgeminiLLMFormatError`
instead of returning `{"_raw": ...}`. Unparseable output is a failure, and
returning something success-shaped guarantees a caller will mishandle it.

**Defence in depth.** `_reject_unusable()` runs before *any* agent result is
persisted, rejecting `_raw` / `_repair_raw` / `_repair_error` / `error` keys,
empty or non-dict payloads, and provider error text hiding inside a
correctly-shaped object.

## Verified behaviour

| Layer | Before | After |
|---|---|---|
| LLM client | Quota text treated as a completion | `CapgeminiLLMQuotaError` raised |
| Discovery | Quota text stored as the artifact, stage COMPLETE | Honest fallback: `generation_mode: deterministic_evidence_only`, provider message recorded as the reason |
| Other agents | Persisted as success | Run status `failed`, no success record, lifecycle does not advance |

**274 tests passing**, including 25 new regression tests that reproduce the
exact production payload.

## UI
The degraded banner now shows the **provider's own message** and turns red for a
quota or billing failure, rather than a generic "AI unavailable" that hides an
actionable problem.

## Action required after deploying

1. **Your LLM quota is exhausted** until 2026-08-30 23:00 UTC. Until then every
   stage will run in deterministic evidence-only mode — clearly labelled, but
   not AI analysis. Raise the tier or supply a different provider.
2. **The KSC engagement is contaminated.** Its Discovery and Architecture
   artifacts contain the quota message. Re-run both stages once quota is
   restored; the guard now prevents a repeat.
3. Consider configuring a **second provider** — the v2 gateway supports
   automatic failover via `LLM_PROVIDERS=primary:...,backup:...`, so a quota
   exhaustion on one provider no longer degrades the whole platform.
