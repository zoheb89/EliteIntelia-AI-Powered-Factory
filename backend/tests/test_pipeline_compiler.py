"""Transformation Studio compiler: visual DAG -> dbt + PySpark + lineage."""
import pytest

from c_invent.services.pipeline_compiler import (
    compile_pipeline, starter_pipeline, topological_order, PipelineError,
)


def test_starter_pipeline_compiles():
    r = compile_pipeline(starter_pipeline())
    assert r["ok"] is True
    assert r["errors"] == []
    assert r["order"] == ["raw_orders", "stg_orders_valid", "fct_customer_revenue"]
    assert r["stats"]["models"] == 3


def test_models_use_dbt_ref_and_source():
    r = compile_pipeline(starter_pipeline())
    by_name = {m["name"]: m["sql"] for m in r["models"]}
    assert "{{ source('raw', 'orders') }}" in by_name["raw_orders"]
    assert "{{ ref('raw_orders') }}" in by_name["stg_orders_valid"]
    assert "{{ ref('stg_orders_valid') }}" in by_name["fct_customer_revenue"]


def test_materialization_and_schema_config():
    r = compile_pipeline(starter_pipeline())
    gold = next(m for m in r["models"] if m["name"] == "fct_customer_revenue")
    assert "materialized='table'" in gold["sql"]
    assert "schema='gold'" in gold["sql"]


def test_aggregate_generates_group_by():
    sql = next(m["sql"] for m in compile_pipeline(starter_pipeline())["models"]
               if m["name"] == "fct_customer_revenue")
    assert "sum(amount) as total_revenue" in sql
    assert "group by customer_id" in sql


def test_schema_yml_contains_tests():
    yml = compile_pipeline(starter_pipeline())["schema_yml"]
    assert "version: 2" in yml
    assert "- not_null" in yml and "- unique" in yml
    assert "sources:" in yml


def test_pyspark_is_generated():
    spark = compile_pipeline(starter_pipeline())["pyspark"]
    assert "SparkSession" in spark
    assert 'spark.read.table("raw.orders")' in spark
    assert ".groupBy(" in spark


def test_column_lineage_traces_through_layers():
    lin = compile_pipeline(starter_pipeline())["lineage"]
    pairs = {(l["from"], l["to"]) for l in lin}
    assert ("raw_orders.order_id", "stg_orders_valid.order_id") in pairs
    assert ("stg_orders_valid.customer_id", "fct_customer_revenue.customer_id") in pairs


def test_cycle_is_reported_not_raised():
    p = starter_pipeline()
    p["edges"].append({"id": "bad", "source": "n3", "target": "n1"})
    r = compile_pipeline(p)
    assert r["ok"] is False
    assert any("cycle" in e.lower() for e in r["errors"])


def test_empty_pipeline_is_handled():
    r = compile_pipeline({"nodes": [], "edges": []})
    assert r["ok"] is False
    assert r["models"] == []


def test_duplicate_names_are_disambiguated():
    p = {
        "name": "dupes",
        "nodes": [
            {"id": "a", "type": "source", "name": "orders", "position": {"x": 0, "y": 0},
             "config": {"source_name": "raw", "table": "orders"}, "columns": []},
            {"id": "b", "type": "source", "name": "orders", "position": {"x": 0, "y": 90},
             "config": {"source_name": "raw", "table": "orders2"}, "columns": []},
        ],
        "edges": [],
    }
    names = [m["name"] for m in compile_pipeline(p)["models"]]
    assert len(set(names)) == 2


def test_node_without_upstream_reports_error():
    p = {
        "name": "orphan",
        "nodes": [{"id": "f", "type": "filter", "name": "lonely_filter",
                   "position": {"x": 0, "y": 0}, "config": {"predicate": "1=1"}, "columns": []}],
        "edges": [],
    }
    r = compile_pipeline(p)
    assert r["ok"] is False
    assert any("upstream" in e.lower() for e in r["errors"])


def test_topological_order_rejects_dangling_edge():
    with pytest.raises(PipelineError):
        topological_order([{"id": "a"}], [{"source": "a", "target": "ghost"}])
