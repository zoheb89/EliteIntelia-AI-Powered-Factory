# Verifying the AI provider from the app (v16)

**339 tests passing · TypeScript clean · build clean.**

## The gap

There was no way to answer "is the LLM working?" from inside the app. The v2
endpoints (`/api/v2/llm/*`) test the **gateway**, but the delivery stages call
the **legacy client** — so a passing gateway test proved nothing about what
Discovery would actually get. The only signal was running a stage and reading
the degraded banner afterwards, which costs a call and tells you nothing about
*why*.

## Settings → AI provider

The Settings page now shows what is configured and has a **Test AI provider**
button. It sends one small request through `orch.llm` — the exact client the
delivery stages use — so the result is a true prediction of what Discovery will
get. Deliberately tiny, because the failure most often being diagnosed is a
quota limit.

The important distinction it draws is **reachable vs refused**:

| Result | Meaning | What to do |
|---|---|---|
| **AI provider is working** | Endpoint answered | Nothing — stages will use AI generation |
| **Reachable, but refused** | Endpoint and key are fine; the provider declined (quota, rate limit, credits, policy) | Raise the plan, or declare `LLM_PROVIDERS` so stages fail over instead of degrading |
| **Authentication rejected** | Endpoint reachable, credentials wrong | Check `ELITEINTELIA_LLM_API_KEY` and the auth header |
| **Did not answer in time** | Accepted but timed out | Check model latency and `LLM_TIMEOUT_SECONDS` |
| **Answered, but not usably** | Replied without valid JSON | Check the model name |
| **Endpoint unreachable** | Could not connect | Check the base URL and network egress |

Every failure carries a remedy — a test asserts none can return without one.

## Checking without the UI

```bash
curl -s https://<your-service>.onrender.com/api/ai/status
curl -s -X POST https://<your-service>.onrender.com/api/ai/test
```

`status` reports configuration without spending a call; `test` spends exactly
one. Neither ever returns the API key — a test asserts that.

## What you will see today

Your provider is quota-blocked until the reset. The test will report
**"Reachable, but the request was refused"** with the provider's own message.
That is the useful answer: your endpoint, key and model are all correct, and the
only problem is the plan limit. It also means the failover route is the fix —
declare a second provider and the stages stop degrading:

```bash
LLM_PROVIDERS=primary:openai_compatible,backup:anthropic
LLM_BACKUP_API_KEY=…
LLM_BACKUP_MODEL=…
```
