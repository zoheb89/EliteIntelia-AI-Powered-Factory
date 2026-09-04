# C INVENT 0.1.23 — Synthetic Enterprise Lab MVP

## Added
- Domain/use-case-agnostic Synthetic Enterprise Lab in the Streamlit UI.
- Deterministic synthetic source families: CRM, ERP, Support, Documents, IoT/Streaming.
- Local Bronze → Silver → Gold execution with data-quality and reconciliation evidence.
- Downloadable validation pack containing source CSVs, validation JSON and a Databricks notebook.
- Databricks notebook that creates Bronze/Silver/Gold Delta tables and validation metrics.
- Regression tests for synthetic source generation, pipeline execution and notebook generation.

## Evidence boundary
Synthetic validation proves engineering mechanics only. It does not claim customer-source connectivity, production performance, or equivalence with customer outputs.

## Test result
38 automated tests passed.
