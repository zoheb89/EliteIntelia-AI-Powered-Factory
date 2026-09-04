# C INVENT Architecture

## Control Plane
The C INVENT Control Plane is the delivery governance layer. It owns project identity, lifecycle state, evidence lineage, readiness gates, approvals, policy checks, audit history and the recommendation of the next action. It does **not** perform stage delivery work.

## Delivery Workspace
The Delivery Workspace is where users and controlled agents perform the lifecycle work: Intake & Documents, Discovery, Environment Assessment, Current-State Assessment, Solution Blueprint, Metadata, Engineering and Validation. Each workspace consumes upstream evidence and produces persisted artifacts/runs for the Control Plane.

## Platform Workspace
The Platform Workspace contains target-platform onboarding, implementation and consumption capabilities. The target is selected per engagement; C INVENT does not assume Databricks, Fabric, Snowflake or another platform. Concrete mutations are invoked only through the selected platform adapter and remain behind approval and the mutation gate.

## AI / Intelligence
Capgemini GPT-5.1 is called through the supplied Generative Engine `/v2/llm/invoke` endpoint. AI agents accelerate discovery, architecture, metadata and engineering, but an AI response is not itself treated as evidence or approval. The evidence-based Current-State Assessment does not require an LLM call.

## Execution Plane
The selected customer data platform is reached only through a controlled platform adapter or approved cloud/IaC execution path. The LLM never receives raw platform credentials. C INVENT converts approved structured plans into controlled platform operations.

## Lifecycle
Intake → Discovery → Environment Assessment → Assessment → Architecture → Platform Onboarding → Metadata → Engineering → Validate → Deploy → Operate

## Project identity
C INVENT never creates an `Untitled Customer Project` during application startup. A customer/project must be explicitly named through **New Customer Project**. Existing POC-era Untitled records are migrated in place so evidence, artifacts, approvals and audit history retain the same project id.

## Data engineering
Source → Ingestion/Lakeflow → Bronze → Silver → Gold → Semantic/AI/BI/Genie. For operational application use cases: curated data → Lakebase → Databricks App.

## Safety
- mutation gate disabled by default
- approval recorded before mutation
- audit event for AI and Databricks actions
- capability discovery before recommending live resources
- no secrets committed to GitHub
