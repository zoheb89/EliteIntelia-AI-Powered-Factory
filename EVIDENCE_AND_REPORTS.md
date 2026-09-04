# Evidence Ingestion + PDF Reports (Increment 5)

Closes the last two gaps that stopped this being a genuine click-through: a
non-technical user could not get documents *in*, and nothing came *out* as a
deliverable file.

**249 backend tests passing · TypeScript clean · production build clean.**

---

## Evidence ingestion — §8, §9

Drag-and-drop upload on the Delivery Factory board. Each document is:

| Step | Behaviour |
|---|---|
| **Extracted** | via the existing document-intelligence service; a failure falls back to plain text rather than losing the upload |
| **Hashed** | SHA-256. Re-uploading the same file returns `duplicate: true` and keeps the original — two copies of one document can later contradict each other |
| **Classified** | RFP / RFI / RFQ / SOW / schema / architecture / meeting notes / requirements |
| **Sensitivity-checked** | PHI and PII detection feeding governance (§21) |
| **Chunked** | overlapping chunks with `chars:start-end` locators, so a citation points at something a human can find |

### Classification is deterministic and inspectable
A misclassified RFP changes which extraction rules apply downstream, so this is
weighted pattern matching, not a model call — reproducible and challengeable.
Scores for every candidate type are returned alongside the verdict.

**The filename is only a nudge.** Documents are routinely named badly, so the
body is authoritative. A test asserts that a quotation named
`definitely_an_rfp.pdf` is still classified `rfq`.

### The UI shows what classification decided
Type, confidence, sensitivity and chunk count are displayed on every upload —
because a silent upload that was misclassified would quietly corrupt discovery.

Verified live: `Weqayah_RFP.txt → RFP, HIGH confidence, PHI, 1 chunk, processed`.

## PDF reports — §29

Thirteen report types, each rendered from the **current** canonical state, so a
download can never silently represent an older project version. The Reports
panel shows which are available now and which are still locked, with the
artifacts each one needs.

Two rules the renderer enforces:

**1. Provenance travels into the document.** Statements are printed with the
same FACT / AI INFERENCE / UNKNOWN / RECOMMENDATION marking they carry on
screen, colour-coded, under the heading *"Every statement below carries how it
is known."* A reader outside the tool cannot mistake an inference for a
customer fact (§68).

**2. Gaps are printed, not hidden.** A draft SOW says so on page one:

```
DRAFT — NOT ISSUABLE. 11 section(s) incomplete and 1 open question(s) outstanding.
Sections complete   17 of 28
Objectives          Not yet established. Requires customer input …
```

Reports generated without AI enrichment disclose that on the first page too.

## Verified end-to-end
Uploaded a real RFP through the browser dropzone → classified RFP/HIGH/PHI →
progress advanced **1/20 → 2/20** as the evidence stage was satisfied → ran
Discovery → downloaded the Discovery PDF (`HTTP 200`, valid, branded).

## A defect found while testing
`<font color="0e7f8c">` threw `Invalid color value` — reportlab requires a `#`
prefix, and `colors.hexval()` returns `0x0e7f8c`. Every report carrying a
provenance table would have failed to render. Fixed and covered by
`test_provenance_travels_into_the_pdf`.

## New API
| Endpoint | Purpose |
|---|---|
| `POST /api/v2/projects/{id}/evidence` | Upload, extract, classify, chunk |
| `GET /api/v2/projects/{id}/evidence` | Evidence index with classification |
| `GET /api/v2/projects/{id}/reports` | Which reports are available now |
| `GET /api/v2/projects/{id}/reports/{kind}.pdf` | Download a report |

Uploads are capped at 25 MB and rejected if empty.

## Still not built
Domain packs (§53) · customer portal (§51-52) · platform adapters (§16) ·
vector search (retrieval is keyword-based) · delivery digital twin (§56) ·
DOCX/PPTX/XLSX output (PDF only) · auth migration onto the new tenant tables.
