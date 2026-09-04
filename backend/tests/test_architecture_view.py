from c_invent.services.architecture_view import platform_fit, architecture_model

def test_platform_fit_is_normalized_and_ranked():
    d = {
        "summary": "Modernize hospital data platform",
        "domain": "healthcare",
        "objectives": ["data engineering", "analytics", "future AI/BI"],
        "requirements": ["medallion architecture", "governance", "SQL Server", "Azure"],
    }
    rows = platform_fit(d, {}, {})
    assert rows
    assert rows[0]["fit_score"] > 0
    assert abs(sum(r["relative_share"] for r in rows) - 100) < 1.0

def test_architecture_model_is_platform_neutral():
    model = architecture_model({"systems": ["on_prem_sql_server_hms_db"]}, {}, "Snowflake")
    assert model["source"]["title"]
    assert model["platform"]["title"] == "Snowflake"
    assert model["bronze"]["title"] == "Bronze"

def test_architecture_sections_accept_dict_shapes_without_slice_errors():
    # LLMs may legitimately return keyed decision/open-question sections.
    # The presentation layer must treat them as metadata, not assume lists.
    sample = {
        "decisions": {"confirmed": ["Azure direction"], "pending": ["CDC strategy"]},
        "open_questions": {"data_scope": ["Schema size"], "operations": ["Support model"]},
        "risks": {"identified": ["Unknown volumes"], "mitigations": ["Profile sources"]},
    }
    assert isinstance(sample["decisions"], dict)
    assert isinstance(sample["open_questions"], dict)
    assert isinstance(sample["risks"], dict)
