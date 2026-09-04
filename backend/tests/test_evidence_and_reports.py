"""Evidence ingestion + classification (§8, §9) and PDF reports (§29)."""
import io
import json
import os
import tempfile

import pytest

from core.evidence import chunk, classify, ingest, sha256
from core.reports import REPORTS, available_reports, build_report


@pytest.fixture()
def repo():
    from persistence import repository as R
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'e.db')}"
    R.reset_engine()
    R.init_db()
    with R.session_scope() as s:
        t = R.Repository.ensure_tenant(s, "t1", "T1")
        yield R.Repository(s, t.id, "tester")
    os.environ.pop("DATABASE_URL", None)
    R.reset_engine()


RFP = ("REQUEST FOR PROPOSAL. Weqayah invites proposals for HMS modernization. "
       "Mandatory requirements: the bidder shall migrate patient admission and "
       "discharge records from SQL Server. Evaluation criteria weighted 40% technical. "
       "Submission deadline 30 June. Patient diagnosis and clinical data in scope; HIPAA applies.")
RFQ = ("Request for Quotation. Please provide unit price and quantities for 50 licences. "
       "Quotation validity 90 days. Delivery terms DDP.")
NOTES = ("Meeting notes 12 June. Attendees: CIO, Data Lead. Agenda: platform direction. "
         "Action items: confirm volumes. Next steps: workshop.")
SCHEMA = ("CREATE TABLE patients (id INT PRIMARY KEY, name VARCHAR(200)); "
          "Data dictionary: column name, type. FOREIGN KEY references admissions.")


# ------------------------------------------------------- classification §9
@pytest.mark.parametrize("text,expected", [
    (RFP, "rfp"), (RFQ, "rfq"), (NOTES, "meeting_notes"), (SCHEMA, "schema"),
])
def test_document_type_is_detected(text, expected):
    assert classify(text).document_type == expected


def test_classification_ignores_a_misleading_filename():
    """Documents are routinely named badly; the body is authoritative."""
    assert classify(RFQ, "definitely_an_rfp.pdf").document_type == "rfq"


def test_rfi_is_distinguished_from_rfp():
    rfi = ("Request for Information. Please describe your capability. "
           "Vendor questionnaire attached. Information requested by 1 July.")
    assert classify(rfi).document_type == "rfi"


def test_phi_is_detected():
    c = classify(RFP)
    assert c.sensitivity == "phi"
    assert c.sensitivity_signals


def test_pii_is_detected_without_phi():
    c = classify("Collect date of birth and email address under GDPR. Passport required.")
    assert c.sensitivity == "pii"


def test_ordinary_document_is_not_flagged_sensitive():
    assert classify("Quarterly infrastructure cost review and capacity planning.").sensitivity == "normal"


def test_thin_document_gets_low_confidence():
    c = classify("Hello.")
    assert c.confidence == "LOW"
    assert c.document_type in ("notes", "unknown")


def test_empty_document_is_unknown():
    assert classify("").document_type == "unknown"


def test_classification_exposes_its_scores():
    """The reader must be able to challenge the classification."""
    c = classify(RFP)
    assert c.scores["rfp"] > c.scores.get("rfq", 0)
    assert c.signals_matched


# ------------------------------------------------------------- chunking §8
def test_chunks_carry_locators():
    ch = chunk(RFP, size=120, overlap=20)
    assert len(ch) > 1
    assert all(c["locator"].startswith("chars:") for c in ch)


def test_chunks_overlap_so_boundaries_stay_retrievable():
    ch = chunk("A" * 500, size=100, overlap=30)
    starts = [int(c["locator"].split(":")[1].split("-")[0]) for c in ch]
    assert starts[1] < 100, "second chunk must start before the first one ends"


def test_empty_text_produces_no_chunks():
    assert chunk("") == [] and chunk("   ") == []


def test_hash_is_stable_and_distinguishing():
    assert sha256(b"abc") == sha256(b"abc")
    assert sha256(b"abc") != sha256(b"abd")


# ------------------------------------------------------------- ingestion §8
def test_ingest_stores_classified_evidence(repo):
    p = repo.create_project("P", intent="x")
    r = ingest(repo, p.id, "rfp.txt", RFP.encode())
    assert r["duplicate"] is False
    assert r["document_type"] == "rfp"
    assert r["sensitivity"] == "phi"
    assert r["chunks"] > 0
    assert len(repo.list_evidence(p.id)) == 1


def test_reuploading_the_same_file_is_not_duplicated(repo):
    """Two copies of one document can later contradict each other."""
    p = repo.create_project("P", intent="x")
    ingest(repo, p.id, "rfp.txt", RFP.encode())
    again = ingest(repo, p.id, "rfp-copy.txt", RFP.encode())
    assert again["duplicate"] is True
    assert len(repo.list_evidence(p.id)) == 1


def test_different_content_is_ingested_separately(repo):
    p = repo.create_project("P", intent="x")
    ingest(repo, p.id, "a.txt", RFP.encode())
    ingest(repo, p.id, "b.txt", RFQ.encode())
    assert len(repo.list_evidence(p.id)) == 2


def test_sensitive_document_is_classified_confidential(repo):
    p = repo.create_project("P", intent="x")
    ingest(repo, p.id, "rfp.txt", RFP.encode())
    assert repo.list_evidence(p.id)[0].classification == "confidential"


def test_ingest_records_an_audit_entry(repo):
    p = repo.create_project("P", intent="x")
    ingest(repo, p.id, "rfp.txt", RFP.encode())
    assert any(e.action == "evidence.added" for e in repo.list_audit(p.id))


def test_evidence_unblocks_the_lifecycle(repo):
    """Regression: attaching evidence must satisfy the evidence stage."""
    from agents_v2.orchestrator import Orchestrator
    from llm.gateway.gateway import LLMGateway
    p = repo.create_project("P", intent="Modernize the platform")
    orch = Orchestrator(LLMGateway())
    assert not orch.lifecycle_state(repo, p.id).is_complete("evidence")
    ingest(repo, p.id, "rfp.txt", RFP.encode())
    assert orch.lifecycle_state(repo, p.id).is_complete("evidence")


# ---------------------------------------------------------------- PDFs §29
PROJECT = {"name": "Weqayah HMS", "domain": "healthcare", "version": 3,
           "intent": "Modernize the HMS data platform."}
STATEMENTS = [
    {"ref": "R-1", "text": "Migrate from SQL Server", "provenance": "FACT"},
    {"ref": "", "text": "What are the data volumes?", "provenance": "UNKNOWN"},
    {"ref": "", "text": "Databricks recommended", "provenance": "RECOMMENDATION"},
]


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text() or "" for page in r.pages)


def test_report_renders_a_valid_pdf():
    pdf = build_report("discovery", PROJECT,
                       {"discovery": {"summary": "s", "objectives": ["o1"]}}, STATEMENTS)
    assert pdf[:5] == b"%PDF-"


def test_report_carries_the_canonical_version():
    """A document must never silently represent an older project state."""
    assert "canonical version 3" in _text(
        build_report("discovery", PROJECT, {"discovery": {"summary": "s"}}))


def test_provenance_travels_into_the_pdf():
    body = _text(build_report("discovery", PROJECT, {"discovery": {"summary": "s"}}, STATEMENTS))
    assert "FACT" in body and "UNKNOWN" in body and "RECOMMENDATION" in body


def test_draft_sow_is_marked_on_the_first_page():
    pdf = build_report("sow", PROJECT, {"sow": {
        "issuable": False,
        "completeness": {"complete_count": 17, "total_sections": 28,
                         "open_questions": 1, "reason": "11 sections incomplete."},
        "sections": {"executive_summary": "Estimated at 218 days."},
        "open_questions": ["What are the volumes?"]}})
    from pypdf import PdfReader
    first = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "DRAFT" in first and "NOT ISSUABLE" in first


def test_issuable_sow_has_no_draft_banner():
    body = _text(build_report("sow", PROJECT, {"sow": {
        "issuable": True,
        "completeness": {"complete_count": 28, "total_sections": 28,
                         "open_questions": 0, "reason": "Ready to issue."},
        "sections": {"executive_summary": "Complete."}, "open_questions": []}}))
    assert "NOT ISSUABLE" not in body


def test_degraded_generation_is_disclosed():
    body = _text(build_report(
        "assessment", PROJECT,
        {"assessment": {"summary": "s", "generation_mode": "deterministic_evidence_only"}},
        degraded_note="Produced without AI enrichment."))
    assert "without AI enrichment" in body


def test_empty_artifact_does_not_crash():
    pdf = build_report("architecture", PROJECT, {"architecture": {}})
    assert pdf[:5] == b"%PDF-"


def test_unknown_report_kind_still_renders():
    assert build_report("something_new", PROJECT, {"something_new": {"a": 1}})[:5] == b"%PDF-"


def test_available_reports_reflect_what_exists():
    av = {r["kind"]: r["available"] for r in available_reports({"discovery", "sow"})}
    assert av["discovery"] is True and av["sow"] is True
    assert av["architecture"] is False


def test_every_report_declares_artifacts_that_agents_produce():
    """A report drawing on an artifact nothing emits could never be generated."""
    from agents_v2.orchestrator import AGENTS
    emitted = {"estimate", "automation_assessment", "sow", "commercial",
               "intent", "evidence_index"}
    for cls in AGENTS.values():
        produces = getattr(cls, "produces", None)
        if produces:
            emitted.add(produces)
    emitted |= {"discovery", "question_set", "assessment", "requirements",
                "platform_options", "platform_decision", "architecture",
                "metadata", "work_packages"}
    for kind, spec in REPORTS.items():
        missing = [a for a in spec["artifacts"] if a not in emitted]
        assert not missing, f"report '{kind}' needs artifacts nothing emits: {missing}"
