"""Requirement extraction from spreadsheet evidence (spec §8, §9).

Driven by a real case: a customer uploaded a 38 KB RFI tracker and discovery
returned nothing useful. Prose extraction only matches modal verbs, so a cell
reading "Real-time parcel tracking" was invisible — even though a tracker is the
most structured evidence a bid team has.
"""
import pytest

from core.tabular_intake import (
    extract_documents, extract_table, split_sheets, summarize,
)

TRACKER = """## SHEET: RFI Tracker
InfiniteSPL POC RFI Tracker v1.2,,,,
Prepared for Saudi Post,,,,
Req ID,Requirement,Category,Priority,Vendor Response
R-001,Real-time parcel tracking across the network,Functional,High,Supported natively
R-002,Integration with existing SAP logistics module,Integration,High,
R-003,Bulk address validation for Saudi addressing,Data Quality,Medium,Partially supported
R-004,Role-based access for branch and HQ users,Security,High,

## SHEET: Commercial
Item,Description,Cost
1,Licences,TBD
2,Support,TBD
"""


def _docs(text=TRACKER, name="tracker.xlsx"):
    return [{"name": name, "text": text}]


# --------------------------------------------------------------- structure
def test_sheets_are_split():
    sheets = [name for name, _ in split_sheets(TRACKER)]
    assert sheets == ["RFI Tracker", "Commercial"]


def test_text_without_sheet_markers_is_treated_as_one_sheet():
    assert len(split_sheets("a,b\n1,2\n3,4")) == 1


def test_empty_text_yields_no_sheets():
    assert split_sheets("") == []


# ------------------------------------------------------------- extraction
def test_requirements_are_extracted_from_a_tracker():
    r = extract_documents(_docs())
    assert r["found"] is True
    assert r["requirement_count"] == 4


def test_rows_without_modal_verbs_are_still_extracted():
    """The exact failure: prose matching finds none of these."""
    texts = [q["text"] for q in extract_documents(_docs())["requirements"]]
    assert "Real-time parcel tracking across the network" in texts
    assert not any(w in " ".join(texts).lower() for w in (" shall ", " must "))


def test_title_rows_above_the_header_are_skipped():
    """Trackers usually carry a title block before the real header row."""
    texts = [q["text"] for q in extract_documents(_docs())["requirements"]]
    assert not any("InfiniteSPL POC RFI Tracker" in t for t in texts)


def test_identifier_category_and_priority_are_captured():
    first = extract_documents(_docs())["requirements"][0]
    assert first["ref"] == "R-001"
    assert first["category"] == "Functional"
    assert first["priority"] == "High"


def test_each_requirement_carries_a_citable_locator():
    for q in extract_documents(_docs())["requirements"]:
        assert "RFI Tracker!row" in q["locator"]


def test_answered_and_unanswered_rows_are_counted():
    """A bid team's first question is what still needs answering."""
    r = extract_documents(_docs())
    assert r["answered_count"] == 2
    assert r["unanswered_count"] == 2


def test_categories_are_aggregated():
    assert extract_documents(_docs())["categories"] == {
        "Functional": 1, "Integration": 1, "Data Quality": 1, "Security": 1}


def test_non_requirement_sheets_are_ignored():
    r = extract_documents(_docs())
    assert all("Commercial" not in t["sheet"] for t in r["tables"])


def test_the_requirement_column_is_reported():
    assert extract_documents(_docs())["tables"][0]["requirement_column"] == "Requirement"


# ------------------------------------------------------------ resilience
def test_a_table_with_no_requirement_column_is_skipped():
    assert extract_table("S", "Item,Cost\n1,100\n2,200") is None


def test_a_table_with_too_few_rows_is_skipped():
    assert extract_table("S", "Requirement\nOnly one row") is None


def test_short_cells_are_not_treated_as_requirements():
    table = extract_table("S", "ID,Requirement\n1,ok\n2,no\n3,A properly stated requirement here")
    assert table is None or all(len(q.text) >= 8 for q in table.requirements)


def test_alternative_header_names_are_recognised():
    text = ("Ref,Description,Section\n"
            "1,Provide nationwide coverage reporting,Reporting\n"
            "2,Support bilingual notifications,Notifications\n")
    r = extract_documents([{"name": "rfp.csv", "text": text}])
    assert r["requirement_count"] == 2


def test_documents_without_tables_are_handled():
    r = extract_documents([{"name": "notes.txt", "text": "Some meeting notes without a table."}])
    assert r["found"] is False and r["requirements"] == []


def test_missing_and_empty_documents_do_not_raise():
    assert extract_documents([])["found"] is False
    assert extract_documents([{"name": "x", "text": ""}])["found"] is False


def test_summary_reports_what_was_found():
    s = summarize(extract_documents(_docs()))
    assert "4 requirement rows" in s and "unanswered" in s


def test_summary_is_empty_when_nothing_was_found():
    assert summarize({"found": False}) == ""


# ------------------------------------------------- integration with discovery
def test_deterministic_discovery_surfaces_table_requirements(monkeypatch, tmp_path):
    """Quota-blocked discovery must still return the customer's own requirements."""
    import os
    monkeypatch.setenv("CINVENT_DB_PATH", str(tmp_path / "d.db"))

    from c_invent.services.config import load_settings
    from c_invent.services.project_store import ProjectStore
    from c_invent.agents.orchestrator import Orchestrator

    store = ProjectStore()
    orch = Orchestrator(load_settings(), store)
    pid = store.create_project(name="saudi post", domain="logistics",
                               description="", source="rfi")
    store.save_document(pid, "tracker.xlsx", "application/vnd.ms-excel",
                        len(TRACKER), TRACKER, {})
    # Discovery correctly refuses to run before an Intake Pack exists.
    orch.capture_intake(pid)

    # Force the degraded path, as a quota exhaustion would.
    def boom(*_a, **_k):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(orch.llm, "invoke_json", boom, raising=False)

    out = orch.run_discovery(pid, "")
    joined = " ".join(out.get("requirements", []))
    assert "Real-time parcel tracking" in joined
    assert "R-001" in joined
    assert out["requirement_table_summary"]["requirement_count"] == 4
    assert any("no response yet" in u for u in out["unknowns"])
