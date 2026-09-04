"""A requirement tracker must be read the way a delivery lead reads it.

Two defects showed up on a real customer tracker: a scope sheet whose label and
prose columns were inverted (the sentence landed in `ref`, truncated to 40
characters, and the label became the requirement), and 41 unanswered "Please
confirm..." rows recorded as evidenced FACTs, so a board full of open questions
reported as fully evidenced.
"""
from core.tabular_intake import extract_documents, is_question_row

INVERTED_SHEET = """## SHEET: Scope Summary
Scope,Position
Duration,Controlled 16-week POC/MVP referenced in the approved scope note and window.
Logical Pipeline,One nominated representative logical workload covering Bronze and Gold.
Fabric Components,Only components needed for the selected workload are in the boundary.
Data Volume,Measured physical volume for selected POC tables to be confirmed later.
"""

RFI_SHEET = """## SHEET: RFI Tracker
Req ID,Question,Category,Response
RFI-001,Please confirm the agreed POC duration and delivery window.,Scope,
RFI-002,Please provide the complete source-system list.,Sources,
RFI-022,Please validate the ~14 TB figure.,Data Volume,Confirmed as 14TB raw
RFI-030,The pipeline shall support incremental loading with watermarks.,Engineering,
"""


# ------------------------------------------------ inverted label/prose columns
def test_prose_becomes_the_requirement_not_the_reference():
    rows = extract_documents([{"name": "scope.xlsx", "text": INVERTED_SHEET}])["requirements"]

    assert len(rows) == 4
    texts = [r["text"] for r in rows]
    assert any(t.startswith("Controlled 16-week POC/MVP") for t in texts)
    # The label column is the category, and no row invents a prose "ref".
    assert {r.get("category") for r in rows} >= {"Duration", "Logical Pipeline"}
    for r in rows:
        assert len(r.get("ref", "")) <= 24, f"prose leaked into ref: {r.get('ref')!r}"


def test_no_requirement_is_silently_truncated_to_a_reference():
    rows = extract_documents([{"name": "scope.xlsx", "text": INVERTED_SHEET}])["requirements"]
    # The original defect produced exactly 40-character refs ending mid-word.
    assert not [r for r in rows if len(r.get("ref", "")) == 40]


# --------------------------------------------- questions are not evidenced facts
def test_unanswered_questions_are_separated_from_stated_requirements():
    d = extract_documents([{"name": "rfi.xlsx", "text": RFI_SHEET}])

    assert d["requirement_count"] == 4
    assert d["open_question_count"] == 2          # RFI-001, RFI-002
    assert d["stated_requirement_count"] == 2     # RFI-022 (answered), RFI-030 (declarative)


def test_an_answered_question_is_no_longer_open():
    rows = {r["ref"]: r for r in
            extract_documents([{"name": "rfi.xlsx", "text": RFI_SHEET}])["requirements"]}

    assert rows["RFI-022"].get("is_question", False) is False
    assert rows["RFI-001"]["is_question"] is True


def test_declarative_rows_are_never_treated_as_questions():
    assert is_question_row("The pipeline shall support CDC.", answered=False) is False
    assert is_question_row("Please confirm the retention period.", answered=False) is True
    assert is_question_row("What is the data volume?", answered=False) is True
    assert is_question_row("Please confirm the retention period.", answered=True) is False


# ------------------------------------------- prose is not a requirement table
PDF_PROSE = """KSC Technical / Compliance Automation MVP

Scope
•• Search KSC's existing 100+ compliance documents.
•• Reduce the time and manual effort required to prepare compliance
responses.
Business Outcome
Customer Request -> Manual Reading -> Manual Document Search
Strategic Intent
The MVP is intended as a quick-win proof of business value
transformation.
covering:
"""


def test_pdf_prose_is_not_mined_as_a_requirement_table():
    """Line-per-row reading turned headings and wrapped sentences into rows.

    A real intake PDF produced requirements reading "Business Outcome",
    "covering:" and "responses." — the tail of a sentence split across lines.
    """
    d = extract_documents([{"name": "ksc intake.pdf", "text": PDF_PROSE}])

    assert d["found"] is False
    assert d["requirement_count"] == 0
    assert d["tables"] == []


def test_a_two_column_table_is_still_extracted():
    """The guard must not cost us genuine narrow trackers."""
    d = extract_documents([{"name": "scope.xlsx", "text": INVERTED_SHEET}])
    assert d["requirement_count"] == 4


# --------------------------------------------------- summaries are readable
def test_a_summary_returned_as_an_object_is_flattened():
    """The prompt asks for {"text": ...} objects, so the model returns the
    summary that way; stringifying it printed a dict literal on the board."""
    from agents_v2.base import BaseAgent

    assert BaseAgent.summary_text({"text": "Current state is unclear."}) == \
        "Current state is unclear."
    assert BaseAgent.summary_text([{"text": "One."}, {"text": "Two."}]) == "One. Two."
    assert BaseAgent.summary_text("Plain string.") == "Plain string."
    assert BaseAgent.summary_text(None) == ""
    assert "{" not in BaseAgent.summary_text({"text": "No braces please."})
