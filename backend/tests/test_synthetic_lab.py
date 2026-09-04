from c_invent.services.synthetic_lab import generate_sources, run_local_pipeline, databricks_notebook

def test_synthetic_sources_cover_enterprise_families():
    sources = generate_sources()
    assert {"crm_customers", "erp_products", "erp_orders", "support_tickets", "documents", "iot_events"}.issubset(sources)
    assert len(sources["erp_orders"]) == 1000
    assert len(sources["documents"]) == 120
    assert len(sources["iot_events"]) == 2000

def test_synthetic_pipeline_end_to_end():
    result = run_local_pipeline(generate_sources())
    assert result["status"].startswith("PASS")
    assert result["reconciliation"] is True
    assert result["gold"]["customer_360_rows"] > 0
    assert sum(x["dq_failures"] for x in result["data_quality"]) > 0

def test_databricks_notebook_is_generated():
    code = databricks_notebook()
    assert "bronze_crm_customers" in code
    assert "silver_orders" in code
    assert "gold_customer_revenue" in code
