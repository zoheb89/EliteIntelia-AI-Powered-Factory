# C INVENT 0.1.24 — Universal Intake Engine

## Purpose
Accept arbitrary customer intake without hard-coding a domain: one-line brief, email, meeting notes, RFI/RFP/RFQ, proposal, SOW and mixed attachments.

## Behavior
1. Capture customer-stated intent.
2. Extract supported document text.
3. Classify document type using deterministic signals.
4. Detect candidate domain/use-case/source families as **signals only**.
5. Detect requirement statements and evidence gaps.
6. Detect target-platform direction separately from platform selection/provisioning.
7. Persist an evidence-safe intake run and downloadable evidence pack.
8. Pass the complete evidence set to AI Discovery for validation/enrichment.

## Guardrail
Intake does not approve scope, architecture, platform, source connectivity or production readiness. Missing information becomes a discovery question rather than an invented fact.

## Regression
41 tests passing, including the new universal intake tests.
