from types import SimpleNamespace
from c_invent.agents.orchestrator import Orchestrator

class Store:
    def __init__(self):
        self.runs=[]; self.artifacts=[]; self.audit=[]
    def get_project(self,pid):
        return {"id":pid,"name":"Weqayah Medical Centre","domain":"Healthcare","description":"Modernize HMS"}
    def documents(self,pid): return []
    def latest_run(self,pid,agent,success_only=True):
        data={
          "discovery":{"id":"d1","created_at":"2026-08-21T10:00:00+00:00","output":{
              "summary":"Hospital HMS modernization","objectives":["Modernize data platform"],
              "processes":["Patient Registration","Billing"],"actors":["Hospital IT"],
              "systems":["DataOcean HMS","SQL Server"],"sources":["SQL Server HMS"],
              "requirements":["Bronze Silver Gold","Data quality"],"unknowns":["CDC method","Data volumes"],
              "assumptions":["Azure Databricks target"]}},
          "environment_assessment":{"id":"e1","created_at":"2026-08-21T11:00:00+00:00","output":{
              "summary":"Databricks environment evidence","target_platform":"Databricks",
              "current_environment":["On-prem SQL Server"],"access":{"workspace":"verified"},
              "capabilities":{"configured":True,"jobs":{"ok":True}},"gaps":[],"unknowns":["Unity Catalog permissions"]}}
        }
        return data.get(agent)
    def save_run(self,*args): self.runs.append(args)
    def save_artifact(self,*args): self.artifacts.append(args)
    def add_audit(self,*args): self.audit.append(args)
    def latest_approval(self,*args): return None

def test_assessment_is_deterministic_and_transparent():
    o=Orchestrator(SimpleNamespace(),Store())
    out=o.run_assessment("p1")
    assert out["assessment_type"] == "evidence_based_current_state"
    assert out["decision"] == "CONDITIONAL GO"
    assert "business_use_case" in out["dimensions"]
    assert "data_and_sources" in out["dimensions"]
    assert "platform_and_environment" in out["dimensions"]
    assert "governance_and_delivery" in out["dimensions"]
    assert out["traceability"]["ai_dependency"] == "not required for lifecycle progression"
    assert any(x[1] == "assessment" and x[2] == "success" for x in o.store.runs)
    assert any(x[1] == "assessment" for x in o.store.artifacts)
