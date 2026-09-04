"""Quality of the evidence-only discovery path.

When the provider is out of quota this is the only output a delivery lead
sees, so it has to be defensible. A real customer run surfaced six defects at
once: the stage's own instruction stored as a customer requirement, five
unrelated industries reported as the domain, the same list repeated under two
different headings twice over, raw storage keys shown as unknowns, and
headings glued onto the following sentence.
"""
from c_invent.agents.orchestrator import Orchestrator, _readable
from c_invent.services.universal_intake import analyze_intake

DOC = """Weqayah Discovery Assessment Questionnaire

The patient completes registration and payment procedures, then is directed to the required service
Which users are involved?
The insurance staff verifies eligibility and coverage before the service is provided.
Some insurance approvals must be handled manually through the insurance portal.
Automated daily SQL Server backup to the H: drive is required.
The hospital uses an ERP system and a SQL database. Documents are exchanged via API.
Our retail pharmacy counter also uses the same system.
"""

INSTRUCTION = ("Analyze the supplied engagement evidence and identify the business intent, "
               "processes, actors, systems, sources, requirements, assumptions, unknowns "
               "and next steps.")


class _Store:
    def documents(self, _pid):
        return [{"name": "weqayah.pdf", "text": DOC}]

    def get_project(self, _pid):
        return {"name": "Weqayah", "description": "Assess the current processes and systems."}


def _run():
    orch = Orchestrator.__new__(Orchestrator)
    orch.store = _Store()
    return orch._deterministic_discovery("p1", INSTRUCTION, "Weekly API call limit exceeded.")


# ------------------------------------------------ the instruction is not evidence
def test_the_stage_instruction_never_becomes_a_customer_requirement():
    requirements = " ".join(_run()["requirements"])
    assert "Analyze the supplied engagement evidence" not in requirements
    assert "unknowns and next steps" not in requirements


# ---------------------------------------------------------------- domain focus
def test_only_dominant_domains_are_reported():
    """One passing mention of a pharmacy counter is not a retail engagement."""
    domains = _run()["domain"]
    assert "healthcare" in domains
    assert "retail" not in domains
    assert len(domains) <= 3


# --------------------------------------------------- no field is padded with another
def test_objectives_and_processes_are_not_the_same_list():
    out = _run()
    assert out["processes"] == []
    assert out["objectives"] != out["processes"] or not out["objectives"]


def test_systems_and_sources_are_not_the_same_list():
    out = _run()
    assert out["systems"] == []
    assert out["sources"], "detected source families should still be reported"


def test_detected_themes_are_labelled_as_candidates_not_stated_objectives():
    for objective in _run()["objectives"]:
        assert objective.startswith("Candidate focus area:") \
            or objective.startswith("Confirm business objectives")


# ------------------------------------------------------------ readable output
def test_unknowns_read_as_sentences_not_storage_keys():
    unknowns = _run()["unknowns"]
    assert unknowns
    for u in unknowns:
        assert u not in ("sla", "sample_data", "volume", "security", "acceptance")
        assert " " in u and u.endswith((".", "?")), f"not a sentence: {u!r}"


def test_source_families_are_humanised():
    sources = _run()["sources"]
    assert "SQL database" in sources
    assert "sql_database" not in sources
    assert _readable("ai_ml") == "AI ML"


# ------------------------------------------------------- sentence boundaries
def test_a_heading_is_not_glued_to_the_sentence_that_follows_it():
    for r in _run()["requirements"]:
        assert "Questionnaire The patient" not in r
        assert "service Which users" not in r


def test_line_breaks_survive_normalisation():
    """`_norm` flattened newlines, making the splitter's \\n+ branch dead."""
    out = analyze_intake("", [{"name": "d.txt", "text": DOC}])
    joined = " ".join(out["requirements_signals"])
    assert "Questionnaire The patient" not in joined
