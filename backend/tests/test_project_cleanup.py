from c_invent.services.project_store import ProjectStore


def test_legacy_empty_projects_are_consolidated(tmp_path):
    db = ProjectStore(tmp_path / "cinvent.db")
    old1 = db.create_project("Untitled Customer Project", "Unknown", "", source="legacy")
    old2 = db.create_project("Untitled Customer Project", "Unknown", "", source="legacy")
    keep = db.ensure_single_clean_workspace()
    ids = [p["id"] for p in db.list_projects()]
    assert keep in ids
    assert len(ids) == 1
    assert db.get_project(keep)["source"] == "system"


def test_explicit_blank_project_is_not_deleted(tmp_path):
    db = ProjectStore(tmp_path / "cinvent.db")
    system = db.create_project("Untitled Customer Project", "Unknown", "", source="system")
    user = db.create_project("Untitled Customer Project", "Unknown", "", source="user")
    db.ensure_single_clean_workspace()
    ids = {p["id"] for p in db.list_projects()}
    assert system in ids
    assert user in ids


def test_untitled_evidence_project_is_renamed_not_deleted(tmp_path):
    db = ProjectStore(tmp_path / "cinvent.db")
    pid = db.create_project("Untitled Customer Project", "Healthcare", "Modernize HMS", source="system")
    db.save_artifact(pid, "intake_pack", "Intake Pack", "json", "{}")
    db.migrate_untitled_projects()
    p = db.get_project(pid)
    assert p["name"] == "Healthcare Modernization Project"
    assert p["id"] == pid


def test_empty_startup_does_not_require_untitled_project(tmp_path):
    db = ProjectStore(tmp_path / "cinvent.db")
    assert db.list_projects() == []
    db.migrate_untitled_projects()
    assert db.list_projects() == []


def test_user_untitled_placeholder_is_renamed(tmp_path):
    db = ProjectStore(tmp_path / "cinvent.db")
    pid = db.create_project("Untitled Customer Project", "Unknown", "", source="user")
    db.migrate_untitled_projects()
    p = db.get_project(pid)
    assert p["name"] != "Untitled Customer Project"
    assert p["name"].startswith("New Customer Project")
