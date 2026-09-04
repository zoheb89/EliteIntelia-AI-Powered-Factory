import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def test_business_analysis_factory_builds_traceable_brd_frd_srd():
    from core.ba_factory import build

    result = build(
        {"id": "p1", "name": "Finance Modernisation", "intent": "Modernise finance reporting", "domain": "Finance", "version": 1},
        {"objectives": ["Improve reporting"], "processes": ["Close"], "actors": ["Finance Controller"],
         "systems": ["ERP"], "constraints": ["Customer approval required"], "unknowns": []},
        {"requirements": [{"ref": "R-1", "text": "Produce daily finance reporting", "category": "functional",
                            "priority": "must", "acceptance": "Compare daily report to source", "provenance": "FACT",
                            "evidence": [{"evidence_id": "e1", "locator": "row 4"}]}]},
    )

    assert result["brd"]["business_requirements"][0]["ref"] == "R-1"
    assert result["frd"]["functional_requirements"][0]["source_brd_ref"] == "R-1"
    assert result["srd"]["system_requirements"][0]["source_requirement"] == "R-1"
    assert result["traceability"][0]["srd_refs"] == ["SRD-1"]
    assert result["traceability"][0]["evidence"][0]["evidence_id"] == "e1"


def test_every_catalogue_accelerator_has_an_executable_runtime_action():
    from core.accelerators import CATALOGUE
    from core.accelerator_runtime import action_for

    missing = [a.id for a in CATALOGUE if action_for(a.id) is None]
    assert not missing, f"Accelerators without runtime actions: {missing}"


def test_runtime_actions_are_json_serialisable():
    from core.accelerator_runtime import ACTION_MAP
    json.dumps(ACTION_MAP)
