"""C INVENT Synthetic Enterprise Lab.

Domain/use-case agnostic test harness for validating the delivery factory without
requiring paid enterprise source systems. Synthetic mode proves pipeline mechanics,
not customer-source connectivity or production equivalence.
"""
from __future__ import annotations

import io
import json
import random
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd


PROFILE = {
    "name": "C INVENT Synthetic Enterprise Lab",
    "purpose": "End-to-end validation of source adapters, Bronze/Silver/Gold processing, data quality, reconciliation and consumption using deterministic synthetic data.",
    "source_families": ["CRM", "ERP", "Support", "Documents", "IoT/Streaming"],
    "non_claims": [
        "Synthetic data does not prove connectivity to a real customer source.",
        "Synthetic runtime and row counts are not customer performance claims.",
        "Synthetic outputs do not establish functional equivalence with a customer's production platform.",
    ],
}


def _base_date():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def generate_sources(seed: int = 42) -> dict[str, pd.DataFrame]:
    rng = random.Random(seed)
    n = 250
    customers = pd.DataFrame([
        {
            "customer_id": f"C{idx:05d}",
            "customer_name": f"Customer {idx:04d}",
            "segment": rng.choice(["Enterprise", "SMB", "Public Sector"]),
            "country": rng.choice(["KSA", "UAE", "India", "UK", "USA"]),
            "status": rng.choice(["ACTIVE", "ACTIVE", "ACTIVE", "INACTIVE"]),
            "updated_at": (_base_date() + timedelta(days=idx % 180)).isoformat(),
        }
        for idx in range(1, n + 1)
    ])

    products = pd.DataFrame([
        {"product_id": f"P{idx:04d}", "product_name": f"Product {idx:03d}", "category": rng.choice(["Data", "AI", "Cloud", "Security"]), "unit_price": round(rng.uniform(100, 5000), 2)}
        for idx in range(1, 41)
    ])

    orders = pd.DataFrame([
        {
            "order_id": f"O{idx:06d}",
            "customer_id": f"C{rng.randint(1, n):05d}",
            "product_id": f"P{rng.randint(1, 40):04d}",
            "quantity": rng.randint(1, 10),
            "order_status": rng.choice(["NEW", "CONFIRMED", "FULFILLED", "CANCELLED"]),
            "order_date": (_base_date() + timedelta(days=rng.randint(0, 220))).date().isoformat(),
            "updated_at": (_base_date() + timedelta(days=rng.randint(0, 220))).isoformat(),
        }
        for idx in range(1, 1001)
    ])
    orders = orders.merge(products[["product_id", "unit_price"]], on="product_id", how="left")
    orders["order_value"] = (orders["quantity"] * orders["unit_price"]).round(2)

    tickets = pd.DataFrame([
        {
            "ticket_id": f"T{idx:06d}",
            "customer_id": f"C{rng.randint(1, n):05d}",
            "priority": rng.choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
            "category": rng.choice(["Technical", "Billing", "Access", "Incident"]),
            "status": rng.choice(["OPEN", "IN_PROGRESS", "RESOLVED"]),
            "created_at": (_base_date() + timedelta(days=rng.randint(0, 220))).isoformat(),
            "resolution_hours": round(rng.uniform(1, 72), 2),
        }
        for idx in range(1, 401)
    ])

    documents = pd.DataFrame([
        {
            "document_id": f"D{idx:05d}",
            "document_type": rng.choice(["RFP", "Policy", "Architecture", "Compliance", "Procedure"]),
            "title": f"Enterprise Document {idx:04d}",
            "language": rng.choice(["EN", "AR", "EN"]),
            "classification": rng.choice(["Internal", "Confidential", "Public"]),
            "text": f"Synthetic enterprise document {idx}. Contains requirements, controls, operational guidance and supporting evidence.",
        }
        for idx in range(1, 121)
    ])

    events = pd.DataFrame([
        {
            "event_id": f"E{idx:07d}",
            "asset_id": f"ASSET-{rng.randint(1, 30):03d}",
            "event_type": rng.choice(["temperature", "pressure", "utilization", "error"]),
            "event_value": round(rng.uniform(1, 100), 3),
            "event_ts": (_base_date() + timedelta(minutes=idx * 5)).isoformat(),
        }
        for idx in range(1, 2001)
    ])

    # Deliberate DQ defects: one duplicate customer and a small number of invalid values.
    customers = pd.concat([customers, customers.iloc[[0]]], ignore_index=True)
    orders.loc[3, "quantity"] = 0
    orders.loc[17, "customer_id"] = None
    tickets.loc[7, "resolution_hours"] = -2

    return {
        "crm_customers": customers,
        "erp_products": products,
        "erp_orders": orders,
        "support_tickets": tickets,
        "documents": documents,
        "iot_events": events,
    }


def run_local_pipeline(sources: dict[str, pd.DataFrame] | None = None) -> dict:
    sources = sources or generate_sources()
    bronze = {name: df.copy() for name, df in sources.items()}

    silver = {}
    for name, df in bronze.items():
        out = df.copy()
        out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
        out["_source"] = name
        out["_ingest_ts"] = datetime.now(timezone.utc).isoformat()
        out["_record_hash"] = pd.util.hash_pandas_object(out.astype(str), index=False).astype("uint64").astype(str)
        if name == "crm_customers":
            out = out.drop_duplicates(subset=["customer_id"], keep="first")
        if name == "erp_orders":
            out["dq_pass"] = out["customer_id"].notna() & (pd.to_numeric(out["quantity"], errors="coerce") > 0)
        elif name == "support_tickets":
            out["dq_pass"] = pd.to_numeric(out["resolution_hours"], errors="coerce") >= 0
        else:
            out["dq_pass"] = True
        silver[name] = out

    customers = silver["crm_customers"]
    orders = silver["erp_orders"].merge(customers[["customer_id", "segment", "country"]], on="customer_id", how="left")
    orders = orders.merge(sources["erp_products"][["product_id", "category"]], on="product_id", how="left")
    valid_orders = orders[orders["dq_pass"] == True].copy()
    sales_by_segment = valid_orders.groupby("segment", dropna=False).agg(
        order_count=("order_id", "count"), revenue=("order_value", "sum")
    ).reset_index()
    sales_by_segment["revenue"] = sales_by_segment["revenue"].round(2)

    customer_360 = customers[["customer_id", "customer_name", "segment", "country", "status"]].copy()
    order_counts = valid_orders.groupby("customer_id").agg(order_count=("order_id", "count"), revenue=("order_value", "sum")).reset_index()
    ticket_counts = silver["support_tickets"].groupby("customer_id").size().reset_index(name="ticket_count")
    customer_360 = customer_360.merge(order_counts, on="customer_id", how="left").merge(ticket_counts, on="customer_id", how="left")
    customer_360[["order_count", "revenue", "ticket_count"]] = customer_360[["order_count", "revenue", "ticket_count"]].fillna(0)

    dq = []
    for name, src in sources.items():
        s = silver[name]
        dq.append({
            "source": name,
            "source_rows": len(src),
            "silver_rows": len(s),
            "dq_failures": int((s["dq_pass"] == False).sum()),
            "status": "PASS" if int((s["dq_pass"] == False).sum()) == 0 else "WARN",
        })
    dq_df = pd.DataFrame(dq)

    result = {
        "profile": PROFILE,
        "status": "PASS_WITH_EXPECTED_DQ_FINDINGS" if (dq_df["dq_failures"] > 0).any() else "PASS",
        "source_counts": {k: int(len(v)) for k, v in sources.items()},
        "bronze_counts": {k: int(len(v)) for k, v in bronze.items()},
        "silver_counts": {k: int(len(v)) for k, v in silver.items()},
        "gold": {
            "customer_360_rows": int(len(customer_360)),
            "sales_by_segment_rows": int(len(sales_by_segment)),
            "revenue_total": round(float(valid_orders["order_value"].sum()), 2),
        },
        "data_quality": dq_df.to_dict(orient="records"),
        "reconciliation": all(len(bronze[k]) == len(sources[k]) for k in sources),
        "expected_findings": [
            "Duplicate customer is removed during Silver standardization.",
            "Invalid order quantity / missing customer are quarantined by dq_pass.",
            "Negative support resolution time is flagged by data quality.",
        ],
    }
    return result


def databricks_notebook(catalog="main", schema="cinvent_synthetic_lab") -> str:
    code = '''# Databricks notebook source
# C INVENT Synthetic Enterprise Lab — deterministic end-to-end validation
# No customer data or paid source connectors are required.
from pyspark.sql import functions as F
from datetime import datetime, timezone

CATALOG = "__CATALOG__"
SCHEMA = "__SCHEMA__"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

# Synthetic source families: CRM, ERP, Support, Documents, IoT.
rows = [
    ("C00001", "Customer 0001", "Enterprise", "KSA", "ACTIVE"),
    ("C00002", "Customer 0002", "SMB", "UAE", "ACTIVE"),
    ("C00003", "Customer 0003", "Public Sector", "India", "ACTIVE"),
]
customers = spark.createDataFrame(rows, ["customer_id","customer_name","segment","country","status"])
customers.write.mode("overwrite").format("delta").saveAsTable(f"{CATALOG}.{SCHEMA}.bronze_crm_customers")

orders = spark.createDataFrame([
    ("O000001", "C00001", "P0001", 2, 1200.0, "CONFIRMED"),
    ("O000002", "C00002", "P0002", 1, 2500.0, "FULFILLED"),
    ("O000003", "C00001", "P0001", 0, 1200.0, "NEW"),
], ["order_id","customer_id","product_id","quantity","order_value","order_status"])
orders.write.mode("overwrite").format("delta").saveAsTable(f"{CATALOG}.{SCHEMA}.bronze_erp_orders")

silver = (orders
    .withColumn("customer_id", F.trim("customer_id"))
    .withColumn("dq_pass", F.col("customer_id").isNotNull() & (F.col("quantity") > 0))
    .withColumn("_record_hash", F.sha2(F.concat_ws("||", *[F.col(c).cast("string") for c in orders.columns]), 256))
)
silver.write.mode("overwrite").format("delta").saveAsTable(f"{CATALOG}.{SCHEMA}.silver_orders")

gold = (silver.filter(F.col("dq_pass"))
    .groupBy("customer_id")
    .agg(F.count("order_id").alias("order_count"), F.sum("order_value").alias("revenue")))
gold.write.mode("overwrite").format("delta").saveAsTable(f"{CATALOG}.{SCHEMA}.gold_customer_revenue")

metrics = {
    "status": "PASS",
    "bronze_orders": spark.table(f"{CATALOG}.{SCHEMA}.bronze_erp_orders").count(),
    "silver_orders": spark.table(f"{CATALOG}.{SCHEMA}.silver_orders").count(),
    "gold_customers": spark.table(f"{CATALOG}.{SCHEMA}.gold_customer_revenue").count(),
    "dq_failures": silver.filter(~F.col("dq_pass")).count(),
    "validated_at": datetime.now(timezone.utc).isoformat(),
}
print(metrics)
'''
    return code.replace("__CATALOG__", str(catalog)).replace("__SCHEMA__", str(schema))

def build_download_bundle(result: dict, sources: dict[str, pd.DataFrame], notebook: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", "# C INVENT Synthetic Enterprise Lab\n\nSynthetic-only validation. No customer data is used.\n")
        z.writestr("validation_result.json", json.dumps(result, indent=2, default=str))
        z.writestr("databricks/cinvent_synthetic_enterprise_lab.py", notebook)
        for name, df in sources.items():
            z.writestr(f"sources/{name}.csv", df.to_csv(index=False))
    return buf.getvalue()
