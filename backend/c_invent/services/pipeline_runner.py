"""Execute a compiled Transformation Studio pipeline and return per-node results.

Two engines:

* ``sandbox`` (default) - runs the generated SQL in an in-memory SQLite database
  seeded with synthetic rows derived from each Source node's declared columns.
  This lets an engineer validate pipeline logic, row counts and column shapes
  with no warehouse credentials at all.
* ``databricks`` - submits the same SQL to the customer's SQL warehouse.

Results are always labelled with the engine that produced them, so sandbox
output can never be mistaken for a real warehouse run.
"""
from __future__ import annotations

import random
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

from c_invent.services.pipeline_compiler import compile_pipeline

SAMPLE_ROWS = 8
SEED_ROWS = 60

# {{ ref('x') }} / {{ source('a','b') }} -> concrete sandbox table names.
_REF = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_SOURCE = re.compile(r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_CONFIG = re.compile(r"\{\{\s*config\([^}]*\)\s*\}\}")
_COMMENT = re.compile(r"^\s*--.*$", re.M)


# Warehouse type names inside CAST(...) must be translated for the sandbox.
# SQLite assigns NUMERIC affinity to any unrecognised type name, so
# `cast('cancelled' as string)` silently returns integer 0 and destroys the
# data. Mapping to real SQLite types keeps sandbox results truthful.
_CAST = re.compile(r"\bcast\s*\(\s*(.+?)\s+as\s+([A-Za-z_][A-Za-z0-9_]*(?:\s*\([^)]*\))?)\s*\)", re.I | re.S)


def _sqlite_cast_type(declared: str) -> str:
    d = (declared or "").lower()
    if any(t in d for t in ("int", "serial")):
        return "INTEGER"
    if any(t in d for t in ("decimal", "numeric", "float", "double", "real", "money")):
        return "REAL"
    return "TEXT"


def _rewrite_casts(sql: str) -> str:
    return _CAST.sub(lambda m: f"cast({m.group(1)} as {_sqlite_cast_type(m.group(2))})", sql)


def _resolve_sql(sql: str, sandbox: bool = True) -> str:
    """Strip dbt config/comments and turn jinja refs into plain table names."""
    sql = _CONFIG.sub("", sql)
    sql = _COMMENT.sub("", sql)
    sql = _REF.sub(lambda m: m.group(1), sql)
    sql = _SOURCE.sub(lambda m: f"{m.group(1)}__{m.group(2)}", sql)
    if sandbox:
        sql = _rewrite_casts(sql)
    return sql.strip()


def _sqlite_type(declared: Optional[str]) -> str:
    d = (declared or "").lower()
    if any(t in d for t in ("int", "bigint", "serial")):
        return "INTEGER"
    if any(t in d for t in ("decimal", "numeric", "float", "double", "real")):
        return "REAL"
    return "TEXT"


def _synthetic_value(col: Dict[str, Any], row: int, rnd: random.Random) -> Any:
    """Deterministic-ish synthetic value shaped by the declared column type."""
    name = (col.get("name") or "").lower()
    kind = _sqlite_type(col.get("type"))

    if "status" in name:
        return rnd.choice(["complete", "pending", "cancelled", "shipped"])
    if "email" in name:
        return f"user{row}@example.com"
    if "date" in name or "_at" in name:
        return f"2026-{(row % 12) + 1:02d}-{(row % 28) + 1:02d}"
    if kind == "INTEGER":
        return row + 1 if name.endswith("_id") and "customer" not in name else rnd.randint(1, 25)
    if kind == "REAL":
        return round(rnd.uniform(10, 900), 2)
    return f"{name or 'value'}_{row + 1}"


def _seed_sandbox(conn: sqlite3.Connection, nodes: List[Dict], seed: int = 7) -> List[str]:
    """Create and populate a table for every Source node."""
    rnd = random.Random(seed)
    created: List[str] = []
    for n in nodes:
        if n.get("type") != "source":
            continue
        cfg = n.get("config") or {}
        table = f"{cfg.get('source_name') or 'raw'}__{cfg.get('table') or n.get('name')}"
        cols = n.get("columns") or [{"name": "id", "type": "bigint"}]
        ddl_cols = ", ".join(f'"{c["name"]}" {_sqlite_type(c.get("type"))}' for c in cols)
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'CREATE TABLE "{table}" ({ddl_cols})')
        placeholders = ", ".join("?" for _ in cols)
        rows = [tuple(_synthetic_value(c, i, rnd) for c in cols) for i in range(SEED_ROWS)]
        conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)
        created.append(table)
    conn.commit()
    return created


def _sample(cursor) -> Dict[str, Any]:
    cols = [d[0] for d in (cursor.description or [])]
    rows = cursor.fetchmany(SAMPLE_ROWS)
    return {"columns": cols, "rows": [list(r) for r in rows]}


def run_sandbox(pipeline: Dict[str, Any]) -> Dict[str, Any]:
    """Materialize every model as a SQLite view/table, in dependency order."""
    compiled = compile_pipeline(pipeline)
    if not compiled.get("ok"):
        return {
            "engine": "sandbox",
            "ok": False,
            "errors": compiled.get("errors", []),
            "nodes": [],
            "message": "Pipeline does not compile; fix the errors before running.",
        }

    started = time.monotonic()
    conn = sqlite3.connect(":memory:")
    results: List[Dict[str, Any]] = []
    ok = True

    try:
        seeded = _seed_sandbox(conn, pipeline.get("nodes") or [])
        by_name = {m["name"]: m for m in compiled["models"]}

        for name in compiled["order"]:
            model = by_name.get(name)
            if not model:
                continue
            t0 = time.monotonic()
            sql = _resolve_sql(model["sql"])
            entry: Dict[str, Any] = {"model": name, "layer": model.get("layer"), "type": model.get("type")}
            try:
                conn.execute(f'CREATE TABLE "{name}" AS {sql}')
                count = conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                cur = conn.execute(f'SELECT * FROM "{name}" LIMIT {SAMPLE_ROWS}')
                entry.update({
                    "status": "success",
                    "row_count": count,
                    "sample": _sample(cur),
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                })
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI per node
                ok = False
                entry.update({
                    "status": "failed",
                    "error": str(exc),
                    "sql": sql,
                    "elapsed_ms": int((time.monotonic() - t0) * 1000),
                })
                results.append(entry)
                break  # downstream models depend on this one
            results.append(entry)

        tests = run_tests(conn, pipeline, compiled) if ok else []
    finally:
        conn.close()

    return {
        "engine": "sandbox",
        "ok": ok,
        "errors": [],
        "seeded_tables": seeded,
        "nodes": results,
        "tests": tests,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "message": (
            "Executed against an in-memory sandbox seeded with synthetic rows. "
            "Results validate pipeline logic, not customer data."
        ),
    }


def run_tests(conn: sqlite3.Connection, pipeline: Dict, compiled: Dict) -> List[Dict[str, Any]]:
    """Execute dbt-style generic tests (not_null / unique) against sandbox output."""
    out: List[Dict[str, Any]] = []
    names = {n["id"]: m for n, m in zip(pipeline.get("nodes", []), [None] * len(pipeline.get("nodes", [])))}
    del names  # model names come from the compiled order

    model_names = set(compiled.get("order") or [])
    for node in pipeline.get("nodes") or []:
        model = None
        for m in compiled.get("models", []):
            if m["type"] == node.get("type") and m["name"] in model_names:
                # match on the compiled name derived from this node
                if m["name"].startswith(re.sub(r"[^0-9a-zA-Z_]+", "_", (node.get("name") or "").lower()).strip("_")):
                    model = m
                    break
        if not model:
            continue
        for col in node.get("columns") or []:
            for test in col.get("tests") or []:
                if test not in ("not_null", "unique"):
                    continue
                cname, mname = col.get("name"), model["name"]
                try:
                    if test == "not_null":
                        failed = conn.execute(f'SELECT count(*) FROM "{mname}" WHERE "{cname}" IS NULL').fetchone()[0]
                    else:
                        failed = conn.execute(
                            f'SELECT count(*) FROM (SELECT "{cname}" FROM "{mname}" '
                            f'GROUP BY "{cname}" HAVING count(*) > 1)'
                        ).fetchone()[0]
                    out.append({
                        "model": mname, "column": cname, "test": test,
                        "status": "pass" if failed == 0 else "fail",
                        "failing_rows": failed,
                    })
                except Exception as exc:  # noqa: BLE001
                    out.append({"model": mname, "column": cname, "test": test,
                                "status": "error", "error": str(exc)})
    return out


def run_databricks(pipeline: Dict[str, Any], settings, store=None) -> Dict[str, Any]:
    """Execute the compiled models against a Databricks SQL warehouse."""
    compiled = compile_pipeline(pipeline)
    if not compiled.get("ok"):
        return {"engine": "databricks", "ok": False, "errors": compiled.get("errors", []),
                "nodes": [], "message": "Pipeline does not compile."}

    try:
        from databricks.sdk import WorkspaceClient
    except Exception:
        return {"engine": "databricks", "ok": False, "nodes": [], "errors": [],
                "message": "databricks-sdk is not installed on the API service."}

    host = getattr(settings, "databricks_host", None) or (settings or {}).get("databricks", {}).get("host") if isinstance(settings, dict) else None
    warehouse = None
    try:
        import os
        host = host or os.getenv("DATABRICKS_HOST")
        warehouse = os.getenv("DATABRICKS_WAREHOUSE_ID")
        if not host or not warehouse:
            raise RuntimeError("DATABRICKS_HOST and DATABRICKS_WAREHOUSE_ID must be configured.")
        w = WorkspaceClient()
    except Exception as exc:
        return {"engine": "databricks", "ok": False, "nodes": [], "errors": [],
                "message": f"Databricks is not configured: {exc}"}

    catalog = "main"
    results: List[Dict[str, Any]] = []
    ok = True
    started = time.monotonic()

    for name in compiled["order"]:
        model = next((m for m in compiled["models"] if m["name"] == name), None)
        if not model:
            continue
        schema = model.get("layer") or "default"
        sql = _resolve_sql(model["sql"], sandbox=False).replace(f"{name}", f"{catalog}.{schema}.{name}")
        t0 = time.monotonic()
        try:
            stmt = w.statement_execution.execute_statement(
                warehouse_id=warehouse,
                statement=f"CREATE OR REPLACE VIEW {catalog}.{schema}.{name} AS {sql}",
                wait_timeout="30s",
            )
            results.append({"model": name, "layer": schema, "status": "success",
                            "statement_id": getattr(stmt, "statement_id", None),
                            "elapsed_ms": int((time.monotonic() - t0) * 1000)})
        except Exception as exc:  # noqa: BLE001
            ok = False
            results.append({"model": name, "layer": schema, "status": "failed",
                            "error": str(exc), "elapsed_ms": int((time.monotonic() - t0) * 1000)})
            break

    return {"engine": "databricks", "ok": ok, "errors": [], "nodes": results, "tests": [],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "message": "Executed against the configured Databricks SQL warehouse."}


def run_pipeline(pipeline: Dict[str, Any], engine: str = "sandbox", settings=None, store=None) -> Dict[str, Any]:
    if engine == "databricks":
        return run_databricks(pipeline, settings, store)
    return run_sandbox(pipeline)
