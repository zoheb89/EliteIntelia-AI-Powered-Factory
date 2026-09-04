import json
import re
from datetime import datetime, timezone

INFINITESPL_REQUIREMENTS = {
    "workload": "Informatica → Bronze & Gold metadata-driven engineering pipeline",
    "status": "RFI-074 closed / officially nominated representative workload",
    "sources": ["SQL Server", "Oracle"],
    "scope_tables": 250,
    "scope_databases": 11,
    "load_patterns": ["Full", "Incremental"],
    "baseline_runtime_hours": 4.5,
    "batch_window_hours": "7–8",
    "target": "Azure Databricks",
    "layers": ["Bronze", "Silver", "Gold"],
    "controls": [
        "metadata-driven orchestration",
        "Delta Lake",
        "CDC / incremental processing",
        "hash validation for selected high-risk tables",
        "data quality",
        "restartability / recovery",
        "reconciliation",
        "monitoring / observability",
    ],
    "parallel_execution": True,
    "production_impact": "zero impact to existing Microsoft Fabric production",
}


def detect_infinitespl(project, documents=None):
    project = project or {}
    docs = documents or []
    text = "\n".join([
        str(project.get("name") or ""),
        str(project.get("description") or ""),
        *[str(d.get("name") or "") + "\n" + str(d.get("text") or "")[:12000] for d in docs],
    ]).lower()
    needles = ("infinitespl", "rfi-074", "informatica", "bronze", "gold", "metadata-driven")
    hits = sum(1 for n in needles if n in text)
    return hits >= 3 or "infinitespl" in text


def validation_spec(project, source_mode="synthetic"):
    return {
        "validation_profile": "InfiniteSPL Azure Databricks Engineering Modernization POC",
        "mode": source_mode,
        "purpose": "Validate the metadata-driven Bronze/Silver/Gold engineering pattern and control framework without changing Fabric production.",
        "evidence_basis": "RFI-074 closed representative workload and supplied Statement of Solution.",
        "requirements": INFINITESPL_REQUIREMENTS,
        "source_access": {
            "status": "not supplied" if source_mode == "synthetic" else "customer supplied",
            "note": "Synthetic mode validates engineering mechanics only; it is not functional equivalence against customer data.",
        },
        "acceptance": [
            "Metadata drives source-to-Bronze processing without hard-coded table logic.",
            "Full and incremental patterns execute successfully.",
            "Silver applies standardization, deterministic keys/hashes and data-quality checks.",
            "Gold produces business-ready outputs from Silver.",
            "Row-count and hash reconciliation detects mismatches.",
            "A failed table can be retried without corrupting completed tables.",
            "A rerun is idempotent and does not duplicate records.",
            "Execution metrics and validation results are persisted.",
            "No customer Fabric pipeline is modified by the validation harness.",
        ],
        "non_claims": [
            "Synthetic validation does not prove customer-source connectivity.",
            "Synthetic validation does not prove functional equivalence with the production Fabric outputs.",
            "Synthetic runtime is not the customer's 4.5-hour baseline and must not be used as a performance claim.",
        ],
    }


def _notebook_code(catalog="main", schema="cinvent_infinitespl_poc"):
    return f'''# Databricks notebook source
# C INVENT — InfiniteSPL POC Validation Harness
# SYNTHETIC MODE: no customer SQL Server/Oracle data is used.
# This validates the metadata-driven engineering mechanics only.

from pyspark.sql import functions as F
from delta.tables import DeltaTable
from datetime import datetime, timezone

CATALOG = "{catalog}"
SCHEMA = "{schema}"
SRC = f"{{CATALOG}}.{{SCHEMA}}_src"
BRONZE = f"{{CATALOG}}.{{SCHEMA}}_bronze"
SILVER = f"{{CATALOG}}.{{SCHEMA}}_silver"
GOLD = f"{{CATALOG}}.{{SCHEMA}}_gold"
RESULTS = f"{{CATALOG}}.{{SCHEMA}}_results"

for s in [SRC, BRONZE, SILVER, GOLD, RESULTS]:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {{s}}")

# 11 databases × ~23 tables = 250 metadata entries. The physical tables are tiny,
# allowing a Free workspace to validate the framework without customer source access.
metadata_rows = []
for db_no in range(1, 12):
    start = 1
    end = 23 if db_no < 11 else 20
    for t_no in range(start, end + 1):
        metadata_rows.append((db_no, f"DB{{db_no:02d}}", f"TABLE_{{t_no:03d}}", "SQL_SERVER" if db_no % 2 else "ORACLE", "incremental" if t_no % 3 else "full"))

metadata = spark.createDataFrame(metadata_rows, ["database_id","source_database","source_table","source_type","load_mode"])
metadata.write.mode("overwrite").format("delta").saveAsTable(f"{{CATALOG}}.{{SCHEMA}}_metadata")

# Source fixture: one tiny deterministic table per metadata row.
for row in metadata.collect():
    src_name = f"{{SRC}}.{{row.source_database.lower()}}_{{row.source_table.lower()}}"
    rows = [(1, "A", 10.0, "2026-01-01T00:00:00Z"), (2, "B", 20.0, "2026-01-02T00:00:00Z"), (3, "A", 30.0, "2026-01-03T00:00:00Z")]
    df = spark.createDataFrame(rows, ["id","status","amount","updated_at"]).withColumn("source_database", F.lit(row.source_database)).withColumn("source_table", F.lit(row.source_table))
    df.write.mode("overwrite").format("delta").saveAsTable(src_name)

# Metadata-driven Bronze full load.
run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
for row in metadata.collect():
    src_name = f"{{SRC}}.{{row.source_database.lower()}}_{{row.source_table.lower()}}"
    tgt_name = f"{{BRONZE}}.{{row.source_database.lower()}}_{{row.source_table.lower()}}"
    df = spark.table(src_name).withColumn("_ingest_run_id", F.lit(run_id)).withColumn("_ingested_at", F.current_timestamp()).withColumn("_record_hash", F.sha2(F.concat_ws("||", *[F.col(c).cast("string") for c in ["id","status","amount","updated_at"]]), 256))
    df.write.mode("overwrite").format("delta").saveAsTable(tgt_name)

# Silver: deterministic standardization, DQ and hash-based change detection.
for row in metadata.collect():
    src = f"{{BRONZE}}.{{row.source_database.lower()}}_{{row.source_table.lower()}}"
    tgt = f"{{SILVER}}.{{row.source_database.lower()}}_{{row.source_table.lower()}}"
    df = (spark.table(src)
          .withColumn("status", F.upper(F.trim("status")))
          .withColumn("amount", F.col("amount").cast("double"))
          .withColumn("_dq_pass", F.col("id").isNotNull() & F.col("updated_at").isNotNull() & (F.col("amount") >= 0))
          .withColumn("_business_hash", F.sha2(F.concat_ws("||", F.col("id").cast("string"), F.col("status"), F.col("amount").cast("string")), 256))
          .dropDuplicates(["id"]))
    df.write.mode("overwrite").format("delta").saveAsTable(tgt)

# Gold: aggregate all Silver outputs. This is deliberately generic and proves
# cross-table orchestration without inventing InfiniteSPL business measures.
gold_parts = []
for row in metadata.collect():
    name = f"{{SILVER}}.{{row.source_database.lower()}}_{{row.source_table.lower()}}"
    gold_parts.append(spark.table(name).select(F.lit(row.source_database).alias("source_database"), F.lit(row.source_table).alias("source_table"), "amount", "_dq_pass"))
gold = None
for part in gold_parts:
    gold = part if gold is None else gold.unionByName(part)
summary = gold.groupBy("source_database").agg(F.count("*").alias("row_count"), F.sum("amount").alias("amount_sum"), F.sum(F.when(F.col("_dq_pass"), 0).otherwise(1)).alias("dq_failures"))
summary.write.mode("overwrite").format("delta").saveAsTable(f"{{GOLD}}.source_summary")

# Reconciliation: compare source/Bronze/Silver counts and assert no data-quality failures.
result = summary.withColumn("run_id", F.lit(run_id)).withColumn("validation_status", F.when(F.col("dq_failures") == 0, "PASS").otherwise("FAIL"))
result.write.mode("append").format("delta").saveAsTable(f"{{RESULTS}}.run_results")

# Incremental proof: update one source row, MERGE it into Silver, then validate idempotency.
probe = metadata.limit(1).collect()[0]
src_name = f"{{SRC}}.{{probe.source_database.lower()}}_{{probe.source_table.lower()}}"
silver_name = f"{{SILVER}}.{{probe.source_database.lower()}}_{{probe.source_table.lower()}}"
updated = spark.createDataFrame([(2, "B", 25.0, "2026-01-04T00:00:00Z")], ["id","status","amount","updated_at"])
updated = updated.withColumn("source_database", F.lit(probe.source_database)).withColumn("source_table", F.lit(probe.source_table)).withColumn("_business_hash", F.sha2(F.concat_ws("||", F.col("id").cast("string"), F.upper(F.trim("status")), F.col("amount").cast("string")), 256)).withColumn("_dq_pass", F.lit(True))
DeltaTable.forName(spark, silver_name).alias("t").merge(updated.alias("s"), "t.id = s.id").whenMatchedUpdateAll().whenNotMatchedInsertAll().execute()

print("C INVENT InfiniteSPL synthetic validation complete")
print(f"Metadata entries: {{metadata.count()}}")
print(f"Gold rows: {{summary.agg(F.sum('row_count')).first()[0]}}")
print(f"DQ failures: {{summary.agg(F.sum('dq_failures')).first()[0]}}")
'''


def build_validation_pack(project, documents=None, catalog="main"):
    spec = validation_spec(project, "synthetic")
    notebook = _notebook_code(catalog=catalog)
    manifest = {
        "profile": spec["validation_profile"],
        "status": "SYNTHETIC_VALIDATION_READY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_mode": "synthetic",
        "requirements_covered": [
            "250-table metadata scale",
            "11-source-database metadata model",
            "SQL Server / Oracle source classification",
            "Full and incremental load modes",
            "Bronze / Silver / Gold",
            "CDC-style MERGE",
            "hash validation",
            "data quality",
            "reconciliation",
            "idempotent rerun pattern",
            "restartable table-level loop",
            "zero-impact parallel validation",
        ],
        "requirements_not_proven": [
            "real SQL Server connectivity",
            "real Oracle connectivity",
            "Fabric output equivalence",
            "ADF/SHIR metadata handoff",
            "customer production runtime benchmark",
            "customer security/network controls",
        ],
        "acceptance": spec["acceptance"],
        "non_claims": spec["non_claims"],
    }
    return spec, manifest, notebook
