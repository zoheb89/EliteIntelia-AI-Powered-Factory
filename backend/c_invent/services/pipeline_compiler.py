"""Visual pipeline -> executable code compiler.

Turns a node/edge DAG built in the Transformation Studio into real, runnable
artifacts:

  * dbt models (`models/<name>.sql`) using `ref()` / `source()`
  * a dbt `schema.yml` carrying column docs and tests
  * a PySpark job for Databricks/Spark execution
  * column-level lineage derived from the node column mappings

Design notes
------------
The DAG is the single source of truth. Code is always generated from it, so the
visual graph and the emitted code cannot drift apart. Node types map 1:1 to a
compile function, which keeps adding a new component type cheap.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

# Component palette exposed to the UI. `inputs` is the arity the compiler expects.
NODE_TYPES: Dict[str, Dict[str, Any]] = {
    "source": {"label": "Source", "inputs": 0, "category": "extract",
               "description": "A raw table or file registered as a dbt source."},
    "sql": {"label": "SQL Transform", "inputs": 1, "category": "transform",
            "description": "Free-form SELECT over the upstream model."},
    "filter": {"label": "Filter", "inputs": 1, "category": "transform",
               "description": "Row-level predicate (WHERE)."},
    "select": {"label": "Select / Rename", "inputs": 1, "category": "transform",
               "description": "Column projection, rename and cast."},
    "join": {"label": "Join", "inputs": 2, "category": "transform",
             "description": "Join two upstream models on a key."},
    "aggregate": {"label": "Aggregate", "inputs": 1, "category": "transform",
                  "description": "GROUP BY with aggregate measures."},
    "union": {"label": "Union", "inputs": 2, "category": "transform",
              "description": "UNION ALL of two upstream models."},
    "target": {"label": "Target / Materialize", "inputs": 1, "category": "load",
               "description": "Materialize as table/view/incremental."},
}

MATERIALIZATIONS = ["view", "table", "incremental", "ephemeral"]
LAYERS = ["bronze", "silver", "gold"]

# dbt generic tests we surface in the inspector.
COLUMN_TESTS = ["not_null", "unique", "accepted_values", "relationships"]


class PipelineError(Exception):
    """Raised when a DAG cannot be compiled."""


def _slug(value: str, fallback: str = "model") -> str:
    """Make a safe SQL/dbt identifier."""
    s = re.sub(r"[^0-9a-zA-Z_]+", "_", (value or "").strip().lower()).strip("_")
    s = re.sub(r"_+", "_", s)
    if not s or s[0].isdigit():
        s = f"{fallback}_{s}" if s else fallback
    return s


def _node_name(node: Dict[str, Any]) -> str:
    return _slug(node.get("name") or node.get("id") or "model")


def topological_order(nodes: List[Dict], edges: List[Dict]) -> List[str]:
    """Kahn's algorithm. Raises PipelineError on cycles or dangling edges."""
    ids = {n["id"] for n in nodes}
    for e in edges:
        if e.get("source") not in ids or e.get("target") not in ids:
            raise PipelineError(f"Edge references a node that does not exist: {e}")

    indeg: Dict[str, int] = {i: 0 for i in ids}
    adj: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        adj[e["source"]].append(e["target"])
        indeg[e["target"]] += 1

    q = deque(sorted([i for i, d in indeg.items() if d == 0]))
    order: List[str] = []
    while q:
        cur = q.popleft()
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)

    if len(order) != len(ids):
        remaining = sorted(ids - set(order))
        raise PipelineError(f"Pipeline contains a cycle involving: {', '.join(remaining)}")
    return order


def _upstream(node_id: str, edges: List[Dict]) -> List[str]:
    """Inputs in stable order so join/union sides stay deterministic."""
    ins = [e for e in edges if e.get("target") == node_id]
    ins.sort(key=lambda e: (e.get("targetHandle") or "", e.get("source") or ""))
    return [e["source"] for e in ins]


def _ref(name: str) -> str:
    return "{{ ref('" + name + "') }}"


def _column_list(node: Dict[str, Any], alias: str = "") -> str:
    """Render the projection for a node, honouring rename/cast metadata."""
    cols = node.get("columns") or []
    if not cols:
        return f"{alias}.*" if alias else "*"
    parts = []
    prefix = f"{alias}." if alias else ""
    for c in cols:
        src = c.get("source_name") or c.get("name")
        out = c.get("name")
        expr = c.get("expression")
        dtype = c.get("type")
        if expr:
            rendered = expr
        elif dtype:
            rendered = f"cast({prefix}{src} as {dtype})"
        else:
            rendered = f"{prefix}{src}"
        parts.append(rendered if rendered == out and not expr and not dtype else f"{rendered} as {out}")
    return ",\n    ".join(parts)


# --------------------------------------------------------------------------- SQL
def _compile_sql(node: Dict, ups: List[str], names: Dict[str, str]) -> str:
    cfg = node.get("config") or {}
    ntype = node.get("type")

    if ntype == "source":
        src = cfg.get("source_name") or "raw"
        tbl = cfg.get("table") or _node_name(node)
        cols = _column_list(node)
        return f"select\n    {cols}\nfrom {{{{ source('{src}', '{tbl}') }}}}"

    if not ups:
        raise PipelineError(f"'{node.get('name') or node['id']}' has no upstream input.")

    first = _ref(names[ups[0]])

    if ntype == "filter":
        pred = cfg.get("predicate") or "1 = 1"
        return f"select\n    {_column_list(node)}\nfrom {first}\nwhere {pred}"

    if ntype == "select":
        return f"select\n    {_column_list(node)}\nfrom {first}"

    if ntype == "sql":
        # Prophecy-style escape hatch: hand-written SQL still participates in the DAG.
        body = (cfg.get("sql") or "").strip()
        if body:
            return body.replace("{{input}}", first)
        return f"select\n    {_column_list(node)}\nfrom {first}"

    if ntype == "join":
        if len(ups) < 2:
            raise PipelineError(f"Join '{node.get('name')}' needs two inputs.")
        second = _ref(names[ups[1]])
        how = (cfg.get("join_type") or "inner").lower()
        on = cfg.get("on") or "l.id = r.id"
        cols = _column_list(node) if node.get("columns") else "l.*, r.*"
        return f"select\n    {cols}\nfrom {first} as l\n{how} join {second} as r\n  on {on}"

    if ntype == "union":
        if len(ups) < 2:
            raise PipelineError(f"Union '{node.get('name')}' needs two inputs.")
        second = _ref(names[ups[1]])
        return f"select * from {first}\nunion all\nselect * from {second}"

    if ntype == "aggregate":
        group = [g for g in (cfg.get("group_by") or []) if g]
        measures = cfg.get("measures") or []
        rendered = [f"{m.get('fn', 'sum')}({m.get('column', '1')}) as {m.get('alias') or _slug(str(m.get('column', 'metric')))}"
                    for m in measures] or ["count(*) as row_count"]
        sel = ",\n    ".join(group + rendered)
        sql = f"select\n    {sel}\nfrom {first}"
        if group:
            sql += "\ngroup by " + ", ".join(group)
        return sql

    if ntype == "target":
        return f"select\n    {_column_list(node)}\nfrom {first}"

    raise PipelineError(f"Unsupported node type: {ntype}")


def _dbt_config(node: Dict) -> str:
    cfg = node.get("config") or {}
    mat = cfg.get("materialization") or ("view" if node.get("type") != "target" else "table")
    if mat not in MATERIALIZATIONS:
        mat = "view"
    opts = [f"materialized='{mat}'"]
    if node.get("layer") in LAYERS:
        opts.append(f"schema='{node['layer']}'")
    if mat == "incremental" and cfg.get("unique_key"):
        opts.append(f"unique_key='{cfg['unique_key']}'")
    return "{{ config(" + ", ".join(opts) + ") }}"


# ------------------------------------------------------------------------ PySpark
def _compile_pyspark(node: Dict, ups: List[str], names: Dict[str, str]) -> str:
    cfg = node.get("config") or {}
    ntype = node.get("type")
    var = _node_name(node)

    if ntype == "source":
        src = cfg.get("source_name") or "raw"
        tbl = cfg.get("table") or var
        return f'{var} = spark.read.table("{src}.{tbl}")'

    if not ups:
        return f"# {var}: no upstream input"
    up = _slug(names[ups[0]])

    if ntype == "filter":
        return f'{var} = {up}.filter("{cfg.get("predicate") or "1 = 1"}")'

    if ntype in ("select", "target"):
        cols = node.get("columns") or []
        if not cols:
            return f"{var} = {up}"
        exprs = ", ".join(f'"{(c.get("expression") or c.get("source_name") or c.get("name"))} as {c.get("name")}"' for c in cols)
        return f"{var} = {up}.selectExpr({exprs})"

    if ntype == "sql":
        body = (cfg.get("sql") or "").strip()
        if body:
            one_line = " ".join(body.split())
            return f'{up}.createOrReplaceTempView("{up}")\n{var} = spark.sql("""{one_line.replace("{{input}}", up)}""")'
        return f"{var} = {up}"

    if ntype == "join":
        if len(ups) < 2:
            return f"# {var}: join needs two inputs"
        right = _slug(names[ups[1]])
        how = (cfg.get("join_type") or "inner").lower()
        on = cfg.get("on") or "l.id = r.id"
        return f'{var} = {up}.alias("l").join({right}.alias("r"), F.expr("{on}"), "{how}")'

    if ntype == "union":
        if len(ups) < 2:
            return f"# {var}: union needs two inputs"
        return f"{var} = {up}.unionByName({_slug(names[ups[1]])}, allowMissingColumns=True)"

    if ntype == "aggregate":
        group = [g for g in (cfg.get("group_by") or []) if g]
        measures = cfg.get("measures") or [{"fn": "count", "column": "*", "alias": "row_count"}]
        aggs = ", ".join(
            f'F.{m.get("fn", "sum")}("{m.get("column", "*")}").alias("{m.get("alias") or _slug(str(m.get("column", "metric")))}")'
            for m in measures
        )
        if group:
            keys = ", ".join(f'"{g}"' for g in group)
            return f"{var} = {up}.groupBy({keys}).agg({aggs})"
        return f"{var} = {up}.agg({aggs})"

    return f"{var} = {up}"


# ------------------------------------------------------------------------ lineage
def _column_lineage(nodes: List[Dict], edges: List[Dict], names: Dict[str, str]) -> List[Dict]:
    """Coalesce-style column-level lineage from each node's column mappings."""
    by_id = {n["id"]: n for n in nodes}
    out: List[Dict] = []
    for n in nodes:
        ups = _upstream(n["id"], edges)
        for c in (n.get("columns") or []):
            target = f"{names[n['id']]}.{c.get('name')}"
            src_col = c.get("source_name") or c.get("name")
            if not ups:
                out.append({"from": f"source.{src_col}", "to": target,
                            "transform": c.get("expression") or "direct"})
                continue
            for uid in ups:
                up_node = by_id.get(uid)
                up_cols = {x.get("name") for x in (up_node.get("columns") or [])}
                if not up_cols or src_col in up_cols or c.get("expression"):
                    out.append({"from": f"{names[uid]}.{src_col}", "to": target,
                                "transform": c.get("expression") or "direct"})
    return out


# ------------------------------------------------------------------------ compile
def compile_pipeline(pipeline: Dict[str, Any]) -> Dict[str, Any]:
    """Compile a DAG into dbt models, schema.yml, PySpark and lineage.

    Never raises for a *bad* graph: errors are returned in the payload so the UI
    can show them inline next to the offending node.
    """
    nodes: List[Dict] = pipeline.get("nodes") or []
    edges: List[Dict] = pipeline.get("edges") or []
    project = _slug(pipeline.get("name") or "eliteintelia_pipeline", "pipeline")

    if not nodes:
        return {"ok": False, "errors": ["Pipeline is empty. Add a Source node to begin."],
                "models": [], "schema_yml": "", "pyspark": "", "lineage": [], "order": []}

    names = {n["id"]: _node_name(n) for n in nodes}
    # dbt model names must be unique across the project.
    seen: Dict[str, int] = {}
    for nid, nm in list(names.items()):
        if nm in seen:
            seen[nm] += 1
            names[nid] = f"{nm}_{seen[nm]}"
        else:
            seen[nm] = 0

    errors: List[str] = []
    try:
        order = topological_order(nodes, edges)
    except PipelineError as exc:
        return {"ok": False, "errors": [str(exc)], "models": [], "schema_yml": "",
                "pyspark": "", "lineage": [], "order": []}

    by_id = {n["id"]: n for n in nodes}
    models: List[Dict[str, str]] = []
    spark_lines: List[str] = []

    for nid in order:
        node = by_id[nid]
        ups = _upstream(nid, edges)
        try:
            sql = _compile_sql(node, ups, names)
            header = _dbt_config(node)
            models.append({
                "name": names[nid],
                "path": f"models/{node.get('layer') or 'staging'}/{names[nid]}.sql",
                "type": node.get("type"),
                "layer": node.get("layer") or "staging",
                "sql": f"-- Generated by EliteInteliA Transformation Studio\n{header}\n\n{sql}\n",
            })
            spark_lines.append(_compile_pyspark(node, ups, names))
        except PipelineError as exc:
            errors.append(str(exc))

    # ---- schema.yml (dbt docs + tests)
    yml: List[str] = ["version: 2", "", "models:"]
    for nid in order:
        node = by_id[nid]
        yml.append(f"  - name: {names[nid]}")
        desc = (node.get("description") or f"{NODE_TYPES.get(node.get('type'), {}).get('label', 'Model')} generated from the visual pipeline.").replace("\n", " ")
        yml.append(f"    description: \"{desc}\"")
        cols = node.get("columns") or []
        if cols:
            yml.append("    columns:")
            for c in cols:
                yml.append(f"      - name: {c.get('name')}")
                if c.get("description"):
                    yml.append(f"        description: \"{c['description']}\"")
                tests = [t for t in (c.get("tests") or []) if t in COLUMN_TESTS]
                if tests:
                    yml.append("        tests:")
                    for t in tests:
                        if t == "accepted_values" and c.get("accepted_values"):
                            vals = ", ".join(f"'{v}'" for v in c["accepted_values"])
                            yml.append(f"          - accepted_values:\n              values: [{vals}]")
                        elif t == "relationships" and c.get("relationship_to"):
                            yml.append(f"          - relationships:\n              to: ref('{c['relationship_to']}')\n              field: {c.get('relationship_field', 'id')}")
                        else:
                            yml.append(f"          - {t}")

    # ---- sources block
    sources = [by_id[i] for i in order if by_id[i].get("type") == "source"]
    if sources:
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for s in sources:
            grouped[(s.get("config") or {}).get("source_name") or "raw"].append(s)
        yml += ["", "sources:"]
        for src_name, items in grouped.items():
            yml.append(f"  - name: {src_name}")
            yml.append("    tables:")
            for s in items:
                yml.append(f"      - name: {(s.get('config') or {}).get('table') or names[s['id']]}")

    pyspark = "\n".join([
        '"""PySpark job generated by EliteInteliA Transformation Studio.',
        f'Pipeline: {project}',
        'Regenerated from the visual DAG - edit the pipeline, not this file.',
        '"""',
        "from pyspark.sql import SparkSession, functions as F",
        "",
        f'spark = SparkSession.builder.appName("{project}").getOrCreate()',
        "",
        *spark_lines,
        "",
        "# Materialize targets",
        *[f'{names[i]}.write.mode("overwrite").saveAsTable("{by_id[i].get("layer") or "gold"}.{names[i]}")'
          for i in order if by_id[i].get("type") == "target"],
    ])

    test_count = sum(len(c.get("tests") or []) for n in nodes for c in (n.get("columns") or []))

    return {
        "ok": not errors,
        "errors": errors,
        "project": project,
        "order": [names[i] for i in order],
        "models": models,
        "schema_yml": "\n".join(yml) + "\n",
        "pyspark": pyspark + "\n",
        "lineage": _column_lineage(nodes, edges, names),
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "models": len(models),
            "tests": test_count,
            "sources": len(sources),
            "targets": sum(1 for i in order if by_id[i].get("type") == "target"),
        },
    }


def starter_pipeline(name: str = "medallion_pipeline") -> Dict[str, Any]:
    """A working Bronze -> Silver -> Gold example so the canvas is never empty."""
    return {
        "name": name,
        "nodes": [
            {"id": "n1", "type": "source", "name": "raw_orders", "layer": "bronze",
             "position": {"x": 40, "y": 60},
             "description": "Raw orders landed from the source system.",
             "config": {"source_name": "raw", "table": "orders", "materialization": "view"},
             "columns": [
                 {"name": "order_id", "type": "bigint", "tests": ["not_null", "unique"]},
                 {"name": "customer_id", "type": "bigint", "tests": ["not_null"]},
                 {"name": "order_status", "type": "string", "tests": []},
                 {"name": "amount", "type": "decimal(18,2)", "tests": []},
             ]},
            {"id": "n2", "type": "filter", "name": "stg_orders_valid", "layer": "silver",
             "position": {"x": 330, "y": 60},
             "description": "Drop cancelled orders and null keys.",
             "config": {"predicate": "order_status <> 'cancelled' and order_id is not null",
                        "materialization": "view"},
             "columns": [
                 {"name": "order_id", "source_name": "order_id", "tests": ["not_null", "unique"]},
                 {"name": "customer_id", "source_name": "customer_id", "tests": ["not_null"]},
                 {"name": "amount", "source_name": "amount", "tests": []},
             ]},
            {"id": "n3", "type": "aggregate", "name": "fct_customer_revenue", "layer": "gold",
             "position": {"x": 620, "y": 60},
             "description": "Revenue per customer, business-ready.",
             "config": {"group_by": ["customer_id"],
                        "measures": [{"fn": "sum", "column": "amount", "alias": "total_revenue"},
                                     {"fn": "count", "column": "order_id", "alias": "order_count"}],
                        "materialization": "table"},
             "columns": [
                 {"name": "customer_id", "source_name": "customer_id", "tests": ["not_null", "unique"]},
                 {"name": "total_revenue", "source_name": "total_revenue", "tests": ["not_null"]},
                 {"name": "order_count", "source_name": "order_count", "tests": []},
             ]},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
    }
