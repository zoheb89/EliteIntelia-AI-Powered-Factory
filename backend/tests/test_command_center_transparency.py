from pathlib import Path

APP = Path(__file__).parents[1] / "app.py"
CSS = Path(__file__).parents[1] / "c_invent" / "ui" / "styles.py"

def test_command_center_exposes_delivery_evidence():
    text = APP.read_text()
    for phrase in [
        "Delivery evidence & decision trail",
        "Current-State Assessment decision",
        "Architecture decision trail",
        "Discovery + Environment Assessment",
    ]:
        assert phrase in text

def test_metrics_are_explicit_cards_not_truncated_metric_widgets():
    text = CSS.read_text()
    assert ".metric-card" in text
    assert ".metric-value" in text
    assert ".metric-hint" in text

def test_assessment_scope_uses_readable_cards():
    text = CSS.read_text()
    assert ".scope-card" in text
    assert ".scope-title" in text


def test_control_plane_and_workspace_are_explicitly_separated():
    text = APP.read_text()
    assert "CONTROL PLANE" in text
    assert "DELIVERY WORKSPACE" in text
    assert "Control Plane vs Workspace" in text
    assert "does not perform delivery work itself" in text
    assert "Open Assessment Workspace" in text


def test_startup_never_creates_untitled_project():
    text = APP.read_text()
    assert 'store.create_project(\n        "Untitled Customer Project"' not in text
    assert 'store.create_project("Untitled Customer Project"' not in text
