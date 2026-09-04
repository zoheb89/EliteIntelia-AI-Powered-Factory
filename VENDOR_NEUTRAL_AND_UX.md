# Vendor-neutral config + readable documents (v13)

**297 tests passing · TypeScript clean · build clean.**

---

## 1. Capgemini removed from configuration

The product is meant to be LLM-neutral (spec §1), but every configuration name
carried a vendor. `ELITEINTELIA_*` is now the supported prefix.

| Was | Now |
|---|---|
| `CAPGEMINI_LLM_API_KEY` | `ELITEINTELIA_LLM_API_KEY` |
| `CAPGEMINI_LLM_BASE_URL` | `ELITEINTELIA_LLM_BASE_URL` |
| `CAPGEMINI_LLM_MODEL` | `ELITEINTELIA_LLM_MODEL` |
| `CAPGEMINI_LLM_PROVIDER` | `ELITEINTELIA_LLM_PROVIDER` |
| `CAPGEMINI_LLM_AUTH_HEADER` / `_SCHEME` | `ELITEINTELIA_LLM_AUTH_HEADER` / `_SCHEME` |
| `CAPGEMINI_IMAGE_*` | `ELITEINTELIA_IMAGE_*` |
| `CAPGEMINI_WORKSPACE_ID` | `ELITEINTELIA_WORKSPACE_ID` |
| `CAPGEMINI_INCLUDE_WORKSPACE_ID` | `ELITEINTELIA_INCLUDE_WORKSPACE_ID` |

**Your live Render deployment will not break.** Every legacy name is still read
as a fallback, so you can deploy this first and rename the variables afterwards
at your own pace. Each legacy hit logs a one-time migration hint, and
`legacy_variables_in_use()` reports exactly what is left to rename.

A test asserts `load_settings()` no longer *requires* any vendor-named variable,
so the vendor cannot creep back in.

### Changing LLM whenever you like
Combined with the failover bridge, switching or adding a provider is now purely
configuration — no code change:

```bash
LLM_PROVIDERS=primary:openai_compatible,backup:anthropic
LLM_PRIMARY_ENDPOINT=…   LLM_PRIMARY_API_KEY=…   LLM_PRIMARY_MODEL=…
LLM_BACKUP_API_KEY=…     LLM_BACKUP_MODEL=…
```

Supported kinds: `openai_compatible` (OpenAI, Azure OpenAI, vLLM, Ollama, most
private gateways), `anthropic`, `google`, `bedrock`.

## 2. Artifacts render as documents, not JSON

A business stakeholder cannot read `{"objectives": [...]}`. Artifacts now render
as a structured document:

- **Summary** in prose at the top, with a clear amber banner when the content
  was produced without AI enrichment
- **Sections as cards** — Objectives, Actors, Systems, Requirements, Risks,
  Unknowns, Next Steps — each with an icon, a count and a meaning-appropriate
  colour
- **Provenance on every item** (FACT / CUSTOMER / AI / ASSUMED / UNKNOWN) so the
  reader can see what rests on evidence
- **Assessment dimensions** as a status grid, colour-coded READY / PARTIAL /
  AT RISK / UNKNOWN
- **Architecture** as a left-to-right layered flow of real component cards
- **Platform fit** as comparison bars with the recommendation marked

Raw JSON remains one click away for engineers.

Verified on a real discovery artifact: **7 readable sections, 8 provenance
badges**, no JSON in the default view.

## 3. Navigation ordered by delivery flow, and static

The sidebar previously listed pages in the order they were built. It now follows
how an enterprise programme actually runs, with group headings:

```
OVERVIEW            Home · Delivery Factory · Engagements
CAPTURE & DISCOVER  Intake Center · Discovery & Assess
DESIGN & DECIDE     Platform Decision · Architecture · Platform & Environment
BUILD               Data & Engineering · Transformation Studio · AI & Analytics
ASSURE & RELEASE    Validation & QA · Deploy & Activate · Monitoring
COMMERCIAL          Effort & Automation · Statement of Work
PLATFORM            Knowledge Center · Settings
```

The sidebar is now `position: sticky` with its own scroll, so it stays put
instead of floating with the page.

## 4. Cloud is a dropdown, not free text

Free text produced values like `azure `, `MS Azure` and `Azure/AWS`, which the
platform-fit engine could not match against its cloud catalogue. Cloud is now a
select (Azure · AWS · Google Cloud · On-premises · Hybrid · Multi-cloud · Not
decided), and choosing one reveals a **region** dropdown filtered to that cloud.

## A defect found while testing
The new renderer showed *"no readable content"* for artifacts whose fields were
all scalars — the empty check ran before the key-value section could render, so
real content was hidden behind a false message. Fixed.

## Still open
Generated **images/diagrams** (the architecture view is rendered HTML, not an
image asset) · DOCX/PPTX export · domain packs · customer portal · vector search.
