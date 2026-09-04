# Transformation Studio

Visual data engineering inside EliteInteliA — a blend of the four tools you named.

| Product | Capability implemented |
|---|---|
| **Matillion** | Drag-and-drop canvas, component palette (Source, SQL, Filter, Select, Join, Aggregate, Union, Target), pan/zoom/minimap |
| **Prophecy** | The DAG **compiles to real code live** — dbt SQL *and* PySpark. Edit a node, the code regenerates instantly. |
| **Coalesce** | **Column-aware nodes** (each node carries its column list, types, expressions), materialization types, **column-level lineage** |
| **dbt Labs** | Models with `ref()` / `source()`, `{{ config(materialized=…, schema=…) }}`, generic tests (`not_null`, `unique`, `accepted_values`, `relationships`), generated `schema.yml`, topological DAG order |

## How it works

The **DAG is the single source of truth**. Code is always regenerated from it, so
the visual pipeline and the emitted code can never drift apart.

```
Canvas (React Flow)  ──▶  POST /api/studio/compile  ──▶  dbt models + schema.yml
                                                        + PySpark job
                                                        + column lineage
```

### Layout
- **Left** — component palette + live pipeline stats (models / tests / sources / targets)
- **Centre** — DAG canvas (medallion-coloured nodes: bronze / silver / gold) and the generated-code panel with four tabs: **dbt SQL**, **schema.yml**, **PySpark**, **Lineage**
- **Right** — inspector: model name, description, layer, materialization, type-specific config (predicate / join condition / group-by + measures / raw SQL) and the **column editor** with per-column dbt tests

### Saving
**Save & Compile** persists four governed artifacts against the engagement:
`pipeline`, `dbt_project`, `pyspark_job`, `column_lineage` — visible in the
Knowledge Center and any workspace artifact viewer.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/studio/palette` | Node types, materializations, layers, tests, starter pipeline |
| `POST /api/studio/compile` | Stateless compile (used for the live preview) |
| `GET /api/engagements/{id}/pipeline` | Load the saved DAG |
| `POST /api/engagements/{id}/pipeline` | Save DAG + persist generated artifacts |

## Validation
The compiler never crashes on a bad graph — it returns errors in the payload so
the UI can flag the offending node:
- cycle detection (Kahn's algorithm)
- dangling edges
- nodes missing a required upstream input
- node arity enforced on connect (a 1-input node refuses a second edge)
- duplicate model names auto-disambiguated

## Example output

From the starter medallion pipeline:

```sql
-- models/gold/fct_customer_revenue.sql
{{ config(materialized='table', schema='gold') }}

select
    customer_id,
    sum(amount) as total_revenue,
    count(order_id) as order_count
from {{ ref('stg_orders_valid') }}
group by customer_id
```

```python
raw_orders = spark.read.table("raw.orders")
stg_orders_valid = raw_orders.filter("order_status <> 'cancelled'")
fct_customer_revenue = stg_orders_valid.groupBy("customer_id").agg(
    F.sum("amount").alias("total_revenue"), F.count("order_id").alias("order_count"))
```

## Extending
Add a node type in `backend/c_invent/services/pipeline_compiler.py`:
1. add it to `NODE_TYPES` (label, arity, category)
2. handle it in `_compile_sql` and `_compile_pyspark`

The palette, canvas and inspector pick it up automatically — no frontend change needed.
