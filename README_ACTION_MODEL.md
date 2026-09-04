# C INVENT 0.1.19 — Metadata / On-the-Fly Action Model

The delivery lifecycle is action-driven rather than page/button-driven.

Each lifecycle action has a stable ID and metadata: title, purpose, workspace,
expected output, approval requirement and applicability predicate. The current
project state selects the applicable action at runtime. The Command Center
renders the generated action plan from that metadata.

Examples:

- `architecture.generate`
- `architecture.approve`
- `platform.configure`
- `metadata.generate`
- `engineering.generate`
- `validation.run`
- `deployment.approve`

The project evidence remains the source of truth. AI generates the delivery
artifacts; the action model determines what can happen next. Actual resource
mutations remain behind explicit executor/approval boundaries.

This means a new project does not need the application code to know in advance
what the next action is. The action is calculated from the persisted lifecycle
state and evidence chain.
