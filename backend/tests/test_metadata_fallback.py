from types import SimpleNamespace
from c_invent.agents.orchestrator import Orchestrator


class Store:
    def __init__(self):
        self.runs = []
        self.artifacts = []
        self.audits = []

    def latest_run(self, pid, agent, success_only=True):
        data = {
            "discovery": {"created_at": "1", "output": {
                "summary": "hospital modernization", "systems": ["on-prem SQL Server"],
                "sources": ["HMS SQL Server"], "requirements": ["governed analytics"],
                "unknowns": ["table inventory"]}},
            "blueprint": {"created_at": "2", "output": {
                "summary": "Azure lakehouse", "target_architecture": {"platform": "Databricks"},
                "data_flow": ["SQL Server -> Bronze -> Silver -> Gold"]}},
        }
        return data.get(agent)

    def latest_approval(self, pid, artifact_type):
        return {"created_at": "2"} if artifact_type == "blueprint" else None

    def save_run(self, *args):
        self.runs.append(args)

    def save_artifact(self, *args):
        self.artifacts.append(args)

    def add_audit(self, *args):
        self.audits.append(args)


class FailingLLM:
    def invoke_json(self, *args, **kwargs):
        raise RuntimeError("Capgemini gateway timed out")


def test_metadata_timeout_persists_safe_fallback():
    store = Store()
    orch = Orchestrator(SimpleNamespace(), store)
    orch.llm = FailingLLM()

    out = orch.run_metadata("p1")

    assert out["ai_enrichment"] == "not_available_for_this_run"
    assert out["tables"] == []
    assert out["columns"] == []
    assert "HMS SQL Server" in out["sources"]
    assert store.runs[-1][1:3] == ("metadata", "success")
    assert store.artifacts
