from pathlib import Path
import tempfile

from c_invent.services.project_store import ProjectStore


def test_execution_state_is_persisted_and_traceable():
    with tempfile.TemporaryDirectory() as tmp:
        store = ProjectStore(Path(tmp) / "test.db")
        pid = store.create_project("Execution Test", "Finance", "Test", "user")
        eid = store.create_execution(pid, "architecture", 3, "Queued")
        store.update_execution(eid, status="running", current_step="environment_assessment", message="Evaluating environment", completed_steps=0, trace_event={"step":"environment_assessment","status":"running"})
        store.update_execution(eid, status="running", current_step="assessment", message="Building assessment", completed_steps=1, trace_event={"step":"environment_assessment","status":"success"})
        store.update_execution(eid, status="success", current_step="blueprint", message="Architecture complete", completed_steps=3, trace_event={"step":"blueprint","status":"success"})
        item = store.get_execution(eid)
        assert item["status"] == "success"
        assert item["completed_steps"] == 3
        assert any(x["step"] == "environment_assessment" for x in item["trace"])
        assert any(x["step"] == "blueprint" for x in item["trace"])
