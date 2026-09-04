# Requirement extraction from spreadsheets (v14)

**318 tests passing · TypeScript clean · build clean.**

## The problem your Saudi Post run exposed

You uploaded `InfiniteSPL_POC_RFI_Tracker_v1.2_Reviewed.xlsx` — 38 KB, a real
RFI tracker — and Discovery returned nothing useful from it.

The cause was not the quota block. Requirement extraction split text into
sentences and matched **modal verbs**:

```python
if any(k in sl for k in ["must ", "shall ", "should ", "required", …]):
```

An RFI tracker is a *table*. A row reading

| Req ID | Requirement | Category |
|---|---|---|
| R-001 | Real-time parcel tracking across the network | Functional |

contains no modal verb, so the extractor found **zero requirements** in the most
structured evidence a bid team owns.

## What now happens

`core/tabular_intake.py` recognises requirement tables and extracts one
structured requirement per row — deterministically, with no AI:

- **Finds the real header row**, skipping the title block trackers usually carry
- **Detects the requirement column** by name (`requirement`, `description`,
  `question`, `specification`, `criteria`, `capability`, …), and separately
  identifies ID, category, priority and response columns
- **Captures a citable locator** per row (`RFI Tracker!row7`)
- **Counts answered vs unanswered**, which is a bid team's first question
- **Ignores non-requirement sheets** — a Commercial cost sheet is not scope

Verified against a real `.xlsx` while the provider was quota-blocked:

```
7 requirement rows extracted from 1 requirement table, across 6 categories,
4 still unanswered.

  [R-001] Real-time parcel tracking across the network (Functional)
  [R-002] Integration with existing SAP logistics module (Integration)
  [R-003] Bulk address validation for Saudi national addressing (Data Quality)
```

None of those rows has a modal verb. The old path found none of them.

Unanswered rows are also raised as an explicit unknown:
*"4 requirement rows in the supplied tracker have no response yet."*

## In the UI
The document view renders these as the table they came from — Ref, Requirement,
Category, Priority, Response and Source — with unanswered rows marked in amber
and a stats bar showing answered / unanswered / categories.

## Why this matters right now
Your quota does not reset until **2026-08-30**. Until then every stage runs in
evidence-only mode. This change means evidence-only mode still returns the
customer's own requirements, verbatim and cited, instead of a near-empty record.

## A note on the failing test I hit
My first integration test asserted discovery returned requirements and it came
back `{"error": …}`. The code was right and the test was wrong: Discovery
correctly refuses to run before an Intake Pack exists. The test now captures
intake first.

## Still open
Generated **diagram images** (architecture renders as HTML, not an image asset) ·
DOCX/PPTX export · domain packs · customer portal · vector search.
