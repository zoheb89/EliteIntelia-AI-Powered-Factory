"""Executable accelerator runtime for the EliteInteliA Factory.

The catalogue remains declarative. This module gives every catalogue entry a
real action: lifecycle execution, deterministic analysis, or a governed bundle.
It never bypasses lifecycle gates.
"""
from __future__ import annotations

from typing import Any, Dict


# Catalogue ids are stable product capabilities. Actions deliberately point at
# canonical lifecycle APIs rather than duplicating business logic here.
ACTION_MAP: Dict[str, dict] = {
    "rfi_response": {"mode": "stage", "stage": "discovery", "label": "RFI/RFP Discovery"},
    "requirements_traceability": {"mode": "business_analysis", "label": "BRD / FRD / SRD Traceability"},
    "current_state_assessment": {"mode": "stage", "stage": "assessment", "label": "Current-State Assessment"},
    "etl_migration": {"mode": "pipeline", "stages": ["assessment", "architecture", "data", "engineering"], "label": "ETL / Platform Migration"},
    "warehouse_modernisation": {"mode": "pipeline", "stages": ["assessment", "architecture", "data", "engineering"], "label": "Warehouse Modernisation"},
    "pipeline_generation": {"mode": "pipeline", "stages": ["data", "engineering"], "label": "Pipeline Generation"},
    "cdc_incremental": {"mode": "pipeline", "stages": ["data", "engineering"], "label": "CDC & Incremental Loading"},
    "data_quality": {"mode": "pipeline", "stages": ["data", "testing"], "label": "Data Quality & Reconciliation"},
    "streaming": {"mode": "pipeline", "stages": ["architecture", "data", "engineering"], "label": "Streaming & Near-Real-Time"},
    "platform_selection": {"mode": "stage", "stage": "platform", "label": "Platform Selection"},
    "governance_unity": {"mode": "stage", "stage": "governance", "label": "Governance & Lineage"},
    "environment_provisioning": {"mode": "stage", "stage": "platform", "label": "Environment & Connectivity"},
    "ai_use_cases": {"mode": "stage", "stage": "ai", "label": "AI Use Cases & Agents"},
    "ai_governance": {"mode": "bundle", "stages": ["ai", "governance"], "label": "AI Governance & Evaluation"},
    "semantic_model": {"mode": "stage", "stage": "bi", "label": "Semantic Model & Metrics"},
    "application_design": {"mode": "stage", "stage": "application", "label": "Application & Workflow Design"},
    "delivery_lifecycle": {"mode": "bundle", "stages": ["discovery", "requirements", "platform", "architecture", "data", "engineering", "testing", "deployment", "operations"], "label": "End-to-End Delivery Lifecycle"},
    "test_assurance": {"mode": "stage", "stage": "testing", "label": "Test Strategy & Assurance"},
    "operations_handover": {"mode": "stage", "stage": "operations", "label": "Operations & Handover"},
    "cicd_release": {"mode": "stage", "stage": "deployment", "label": "CI/CD & Gated Release"},
    "effort_automation": {"mode": "estimate", "label": "Effort & Automation Analysis"},
    "sow_generation": {"mode": "sow", "label": "SOW & Commercial Pack"},
    "scope_control": {"mode": "scope", "label": "Scope Lock & Change Control"},
}


def action_for(accelerator_id: str) -> dict | None:
    return ACTION_MAP.get(accelerator_id)


def readiness(accelerator_id: str, lifecycle_state) -> dict:
    action = action_for(accelerator_id)
    if not action:
        return {"executable": False, "reason": "Accelerator has no runtime action registered."}
    if action["mode"] == "business_analysis":
        stage = "requirements"
        if not lifecycle_state.is_complete(stage):
            return {"executable": False, "reason": "Requirements must be completed before BRD/FRD/SRD generation."}
        return {"executable": True, "next": stage}
    stages = action.get("stages") or ([action["stage"]] if action.get("stage") else [])
    for stage in stages:
        if lifecycle_state.is_complete(stage):
            continue
        blockers = lifecycle_state.blockers(stage)
        return {"executable": not blockers, "next": stage, "blockers": blockers}
    return {"executable": True, "next": None, "reason": "All accelerator stages are already complete."}
