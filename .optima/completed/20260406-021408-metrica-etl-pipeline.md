# Task: Story 4.1 — Source-to-Target ETL Pipeline (Metrics Computation Engine)

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-06
**Epic**: 4 — Source-to-Target Pipeline
**Priority**: High — transforms Metrica from a DQ checker into a real metric engine

---

## Context & Where We Are

Excellent work on Story 3.1! The codebase now stands at:

```
metrica/
├── registry/        models.py, loader.py          ✅ solid
├── dq/              models.py, store.py, config.py ✅ solid
├── monitoring/      scheduler.py, alerting.py      ✅ just delivered
└── ml_bridge/       __init__.py                    🔲 stub — next after this

scripts/
├── generate_mock_data.py   ✅ 1000-customer dataset with injected DQ issues
├── run_dq_checks.py        ✅ 11 executable checks, scorecard, persists scores
└── run_scheduler.py        ✅ --once / --daemon / --dry-run, cron-ready

tests/                      21 tests, all passing
dq_schedule.yaml            ✅ schedule + alert config
data/metrica_mock.duckdb    ✅ live DB — raw.*, metrics.*, dq.*
definitions/
├── metrics/        tenure_months.yaml, monthly_charges.yaml, support_calls_30d.yaml
├── cdes/           4 CDE YAMLs
└── sources/        crm.yaml, billing.yaml, contact_center.yaml
```

**What's missing**: right now `metrics.customer_metrics` is populated *once* by
`generate_mock_data.py` at setup time. There is no ongoing process that re-computes
metric values from raw source data as time passes. This story builds that engine.

The **ETL pipeline** reads from `raw.*` tables (the source layer), applies the
transformation SQL defined in each metric's YAML, and writes the results back to
`metrics.customer_metrics`. It is the heart of the source-to-target mapping.

---

## What to Build

### 1. `metrica/pipeline/` — New Package

Create a new package alongside `registry/`, `dq/`, `monitoring/`, `ml_bridge/`:

```
metrica/pipeline/
├── __init__.py
├── runner.py       ← main ETL orchestrator
├── transformer.py  ← per-metric SQL execution
└── models.py       ← Pydantic models for run results
```

---

### 2. `metrica/pipeline/models.py` — Pipeline Run Models

```python
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class PipelineStatus(str, Enum):
    success = "success"
    partial = "partial"   # some metrics failed, others succeeded
    failed  = "failed"    # all metrics failed

class MetricRunResult(BaseModel):
    metric_id: str
    rows_read: int          # rows scanned from source
    rows_written: int       # rows upserted into customer_metrics
    duration_seconds: float
    status: PipelineStatus
    error: str | None = None
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class PipelineRunResult(BaseModel):
    run_id: str             # e.g. "etl-run-<uuid4 short>"
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    metrics_attempted: int
    metrics_succeeded: int
    metrics_failed: int
    total_rows_written: int
    status: PipelineStatus
    metric_results: list[MetricRunResult]
```

---

### 3. `metrica/pipeline/transformer.py` — Per-Metric SQL Executor

This is where the source-to-target transformation happens for a single metric.

```python
class MetricTransformer:
    def __init__(self, conn: duckdb.DuckDBPyConnection): ...

    def transform(self, metric: MetricDefinition, dry_run: bool = False) -> MetricRunResult:
        """
        Execute the source-to-target SQL for one metric.

        Flow:
        1. Read source_mappings[0].transformation_sql from metric YAML
        2. Execute it against the DuckDB connection (reads from raw.*)
        3. Upsert results into metrics.customer_metrics
        4. Return MetricRunResult with row counts and timing
        """
```

**Important — how transformation SQL works in the YAMLs:**

Looking at the existing metric YAMLs, `transformation_sql` is a SELECT that computes the
metric value from raw tables. For example, tenure_months.yaml has something like:

```sql
SELECT customer_id,
       DATEDIFF('month', activation_date, CURRENT_DATE) AS tenure_months
FROM raw.crm_customers
WHERE account_status = 'Active'
  AND activation_date IS NOT NULL
```

The transformer should:
1. Execute this SELECT
2. Take the result and UPSERT into `metrics.customer_metrics` (INSERT OR REPLACE / INSERT ... ON CONFLICT UPDATE)
3. Also update `last_updated = CURRENT_TIMESTAMP` for touched rows

**Upsert pattern for DuckDB**:
```sql
INSERT INTO metrics.customer_metrics (customer_id, <metric_col>, last_updated)
    SELECT customer_id, <metric_value>, CURRENT_TIMESTAMP FROM (<transformation_sql>)
ON CONFLICT (customer_id) DO UPDATE SET
    <metric_col> = excluded.<metric_col>,
    last_updated = excluded.last_updated
```

**The column name mapping**: the transformation SQL aliases the computed value to the
metric_id (e.g. `AS tenure_months`). Use `metric.metric_id` as both the SELECT alias
and the target column name in `customer_metrics`.

---

### 4. `metrica/pipeline/runner.py` — ETL Orchestrator

```python
class PipelineRunner:
    def __init__(self, db_path: Path, definitions_root: Path): ...

    def run(
        self,
        metric_ids: list[str] | None = None,   # None = run all
        dry_run: bool = False,
    ) -> PipelineRunResult:
        """
        Orchestrate ETL for all (or selected) metrics.

        Flow:
        1. Load all metric definitions via DefinitionLoader
        2. Open DuckDB connection
        3. For each metric: call MetricTransformer.transform()
        4. Collect MetricRunResult objects
        5. Persist run summary to pipeline_runs table (see below)
        6. Return PipelineRunResult
        """

    def _ensure_pipeline_schema(self, conn): ...
    # Creates pipeline_runs table if not exists
```

**Pipeline runs table** (add to `sql/003_pipeline_schema.sql`):
```sql
CREATE SCHEMA IF NOT EXISTS pipeline;

CREATE TABLE IF NOT EXISTS pipeline.pipeline_runs (
    run_id          VARCHAR PRIMARY KEY,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP NOT NULL,
    duration_seconds DOUBLE NOT NULL,
    metrics_attempted INTEGER NOT NULL,
    metrics_succeeded INTEGER NOT NULL,
    metrics_failed    INTEGER NOT NULL,
    total_rows_written INTEGER NOT NULL,
    status          VARCHAR NOT NULL,
    details_json    VARCHAR    -- JSON-serialized list[MetricRunResult]
);
```

---

### 5. `scripts/run_pipeline.py` — CLI Entry Point

```bash
# Run ETL for all metrics
python3 scripts/run_pipeline.py

# Run for specific metrics only
python3 scripts/run_pipeline.py --metrics tenure_months monthly_charges

# Dry run — show what would be computed, don't write
python3 scripts/run_pipeline.py --dry-run

# Verbose — print row counts per metric
python3 scripts/run_pipeline.py --verbose
```

Output should be clean and informative:
```
Metrica ETL Pipeline
====================
Running 3 metrics...

  ✓ tenure_months       950 rows  (0.12s)
  ✓ monthly_charges    1000 rows  (0.08s)
  ✓ support_calls_30d  1000 rows  (0.11s)

Pipeline complete: 3/3 succeeded | 2950 rows written | 0.31s total
Run ID: etl-run-a3f9c1
```

---

### 6. Integrate with Scheduler

Update `metrica/monitoring/scheduler.py` so that `run_once()` can **optionally** run the
ETL pipeline before DQ checks. Add a flag to `dq_schedule.yaml`:

```yaml
pipeline:
  # Run ETL before DQ checks on every scheduled run?
  run_before_dq: false   # default off — enable when ready
```

When `run_before_dq: true`:
1. `PipelineRunner.run()` executes first
2. Then `run_dq_checks()` runs on freshly computed data
3. Both results appear in the alert file

Keep it **off by default** so existing tests don't break.

---

### 7. `tests/test_pipeline.py` — Tests

```python
def test_pipeline_runner_runs_all_metrics():
    """PipelineRunner.run() returns result with 3 metrics attempted and succeeded."""

def test_pipeline_rows_written():
    """After run(), metrics.customer_metrics has rows for all 3 metrics."""

def test_pipeline_dry_run_no_writes():
    """dry_run=True computes but does not write to DB."""

def test_pipeline_selective_run():
    """run(metric_ids=['tenure_months']) only processes that metric."""

def test_pipeline_run_persisted():
    """pipeline.pipeline_runs has a row after run()."""

def test_pipeline_idempotent():
    """Running pipeline twice gives same row count (upsert, not insert)."""

def test_metric_transformer_single():
    """MetricTransformer.transform() on one metric returns valid MetricRunResult."""

def test_pipeline_partial_failure():
    """If one metric's SQL fails, others still succeed (status=partial)."""
```

---

## Acceptance Criteria

- [ ] `python3 scripts/run_pipeline.py` runs cleanly against `data/metrica_mock.duckdb`
- [ ] `python3 scripts/run_pipeline.py --dry-run` computes without writing to DB
- [ ] `python3 scripts/run_pipeline.py --metrics tenure_months` runs only that metric
- [ ] `metrics.customer_metrics` is correctly populated/updated after a pipeline run
- [ ] `pipeline.pipeline_runs` table created and has a row after each run
- [ ] `sql/003_pipeline_schema.sql` exists with the pipeline schema DDL
- [ ] `metrica/pipeline/` package created with `runner.py`, `transformer.py`, `models.py`
- [ ] ETL is idempotent — running twice gives same results (upsert not insert)
- [ ] `dq_schedule.yaml` updated with `pipeline.run_before_dq: false` section
- [ ] All 8 new pipeline tests pass
- [ ] All 21 existing tests still pass — zero regressions
- [ ] Run `pytest tests/ -v` at the end and confirm full count

## Technical Notes

- Stay inside DuckDB — no new database dependencies
- The transformation SQL in the YAMLs uses `CURRENT_DATE` — this is fine for mock data
- If a metric's transformation SQL produces NULL values (e.g. null activation_date), still upsert the row with NULL — the DQ checks will catch it. Don't silently skip bad rows
- `partial` status = at least 1 metric succeeded AND at least 1 failed
- Keep `PipelineRunner` importable without side effects — schema creation only happens in `run()`
- Use `json.dumps([r.model_dump(mode='json') for r in results])` for `details_json` column
- Error handling: catch per-metric exceptions, log them in MetricRunResult.error, continue to next metric



---
## Agent Response (2026-04-06 02:14:08)
**Outcome**: completed

Story 4.1 — ETL Pipeline: MetricTransformer builds executable SQL from YAML definitions (expression-only + full SELECT), PipelineRunner orchestrates all/selected metrics with idempotent upsert, CLI with --dry-run/--metrics, scheduler integration via run_before_dq config, 9 new tests (30 total passing). Commit 357eb0a.
