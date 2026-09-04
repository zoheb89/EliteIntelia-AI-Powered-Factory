from pathlib import Path


def test_api_server_has_architecture_orchestration():
    text = Path("backend/api_server.py").read_text(encoding="utf-8")
    assert '"architecture": blueprint_success' in text
    assert '"environment_assessment"' in text
    assert '"assessment"' in text
    assert '"blueprint"' in text
    assert '"execution_trace"' in text
    assert '"next_stage": "platform"' in text
