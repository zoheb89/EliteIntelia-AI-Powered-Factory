# C INVENT 0.1.20 Final Fix 5

## Production fixes

### 1. Capgemini metadata timeout no longer blocks the delivery lifecycle
- Metadata now consumes only persisted Discovery + approved Architecture evidence.
- Customer documents are not resent during Metadata generation.
- The request is compact and bounded for the Capgemini gateway.
- If the gateway still times out, C INVENT persists an **evidence-safe deterministic metadata skeleton** as a successful Metadata run.
- No tables, columns, relationships or business definitions are fabricated. Missing schema detail is explicitly recorded as an assumption/open question.
- The provider error is retained for traceability and can be retried later.

### 2. End-to-end lifecycle navigation fixed
- Delivery Workspace navigation is now gate-aware from Intake → Discovery → Environment Assessment → Assessment → Architecture → Platform → Metadata → Engineering.
- Locked stages cannot be opened from the sidebar until their prerequisite persisted evidence/gate exists.
- Completed stages remain clickable for review.
- Each completed stage exposes a persistent **Next stage** hand-off that re-checks the Control Plane state after navigation.
- Metadata retains its Engineering hand-off after a page refresh.

### 3. UI typography normalized
- Unified application/sidebar font family and heading scale.
- Standardized paragraph, label, button and control typography so stage pages use the same visual hierarchy.
- Reduced mixed default Streamlit heading/control sizing.

### 4. Previous Architecture renderer fix retained
- Architecture sections remain tolerant of lists, dictionaries, scalars and nested metadata.
- The previous `arch.get("decisions", [])[:8]` dictionary-slice crash remains fixed.

## Validation

- Python compilation: PASS
- Automated tests: **32 passed**
- Metadata timeout fallback test: PASS
- Architecture dictionary renderer tests: PASS
- Lifecycle action registry tests: PASS

## Deployment recommendation

Deploy this package as the replacement baseline for the earlier 0.1.20 Final Fix packages.
