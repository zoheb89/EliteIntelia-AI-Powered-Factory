from c_invent.services.poc_validation import detect_infinitespl, build_validation_pack

def test_infinitespl_profile_and_synthetic_pack():
    project={"name":"InfiniteSPL Azure Databricks POC","description":"RFI-074 Informatica Bronze Gold metadata-driven SQL Server Oracle"}
    assert detect_infinitespl(project, [])
    spec, manifest, notebook = build_validation_pack(project, [])
    assert manifest["status"] == "SYNTHETIC_VALIDATION_READY"
    assert spec["requirements"]["scope_tables"] == 250
    assert spec["requirements"]["scope_databases"] == 11
    assert "Bronze" in notebook and "Silver" in notebook and "Gold" in notebook
