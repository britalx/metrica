# Task: Story 5.1 — Feature Store Interface + DQ Gate

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-06
**Epic**: 5 — ML Feature Bridge
**Priority**: High — closes the loop from governed metrics to ML-ready features
**Depends on**: Story 4.1 ✅ (ETL pipeline), Story 1.3 ✅ (50 metric registry)

---

## Context & Where We Are

Outstanding work on the last two deliveries. The codebase is now in a strong position:

```
metrica/
├── registry/        models.py, loader.py                    ✅ 50 metrics, 35 CDEs, 6 sources
├── dq/              models.py, store.py, config.py          ✅ 5-dimension scoring, DuckDB-backed
├── monitoring/      scheduler.py, alerting.py               ✅ cron + daemon, markdown alerts
├── pipeline/        runner.py, transformer.py, models.py    ✅ ETL: raw.* → metrics.customer_metrics
└── ml_bridge/       __init__.py                             🔲 STUB — this story fills it

scripts/
├── generate_mock_data.py   ✅ 1000 customers, 5 injected DQ issues
├── run_dq_checks.py        ✅ 11 checks, scorecard, persists scores
├── run_scheduler.py        ✅ --once / --daemon / --dry-run
└── run_pipeline.py         ✅ ETL runner, idempotent, --dry-run

data/metrica_mock.duckdb    schemas: raw.*, metrics.*, dq.*, pipeline.*
tests/                      32 tests, all passing
```

**What's missing**: `metrica/ml_bridge/` is an empty stub. There is no interface
for a data scientist or ML pipeline to say "give me the feature vector for customer X"
or "give me the training dataset for all customers" — with DQ guarantees baked in.

This story builds that interface. It is the **last piece of infrastructure** before
Epic 6 (the actual churn model) becomes buildable.

---

## The Mental Model

```
Raw Data (CRM / Billing / CDR / Network)
         ↓  [Pipeline Runner — Story 4.1]
metrics.customer_metrics  (50 columns, 1 row per customer)
         ↓  [DQ Store — Epic 2]
dq.dq_scores  (per-metric quality scores, updated each run)
         ↓  [Feature Store — THIS STORY]
ml_ready feature vectors  (only metrics that pass DQ gate)
         ↓
Churn Model (Epic 6)
```

The Feature Store sits between the metrics layer and the model layer. Its job:
1. **Select** which metrics are ML-ready (status=active, DQ score ≥ gate threshold)
2. **Gate** — refuse to serve features that fail the DQ gate
3. **Assemble** — return a clean feature matrix (pandas DataFrame or dict)
4. **Explain** — tell callers which features were gated out and why

---

## What to Build

### 1. `metrica/ml_bridge/feature_store.py` — The Core Interface

```python
class FeatureStore:
    def __init__(self, db_path: Path, definitions_root: Path, config: DQConfig | None = None):
        ...

    # ── Single customer ──────────────────────────────────────────────
    def get_features(
        self,
        customer_id: str,
        metric_ids: list[str] | None = None,   # None = all active metrics
        enforce_dq_gate: bool = True,
    ) -> FeatureVector:
        """Return feature values for one customer, with DQ gate applied."""

    # ── Batch / training dataset ─────────────────────────────────────
    def get_feature_matrix(
        self,
        customer_ids: list[str] | None = None,  # None = all customers
        metric_ids: list[str] | None = None,     # None = all active metrics
        enforce_dq_gate: bool = True,
        format: Literal["dict", "records"] = "records",
    ) -> FeatureMatrix:
        """Return feature matrix for multiple customers. Used for model training."""

    # ── DQ Gate inspection ───────────────────────────────────────────
    def gate_status(self) -> GateStatusReport:
        """Show which metrics pass/fail the DQ gate and why."""

    def passed_metrics(self) -> list[str]:
        """metric_ids that currently pass the DQ gate."""

    def blocked_metrics(self) -> list[str]:
        """metric_ids currently blocked by the DQ gate."""
```

---

### 2. `metrica/ml_bridge/models.py` — Pydantic Response Models

```python
from pydantic import BaseModel
from datetime import datetime

class FeatureValue(BaseModel):
    metric_id: str
    value: float | int | bool | None
    dq_score: float | None       # latest composite DQ score for this metric
    dq_status: str               # "pass" | "warn" | "fail" | "unknown"
    gated_out: bool = False      # True if DQ gate blocked this feature

class FeatureVector(BaseModel):
    customer_id: str
    features: list[FeatureValue]
    metrics_requested: int
    metrics_served: int          # = metrics_requested - gated_out count
    metrics_gated: int
    assembled_at: datetime
    dq_gate_threshold: float     # the threshold used

class FeatureRecord(BaseModel):
    """One row in the feature matrix — flat dict of metric_id → value."""
    customer_id: str
    features: dict[str, float | int | bool | None]
    gated_metrics: list[str]     # which metrics were gated for this customer

class FeatureMatrix(BaseModel):
    records: list[FeatureRecord]
    total_customers: int
    total_metrics: int
    metrics_served: list[str]    # metric_ids included in the matrix
    metrics_gated: list[str]     # metric_ids excluded by DQ gate
    gate_threshold: float
    assembled_at: datetime

class GateStatusEntry(BaseModel):
    metric_id: str
    domain: str
    latest_dq_score: float | None
    gate_threshold: float
    passes_gate: bool
    blocking_dimension: str | None   # which dimension caused failure, if any
    last_checked: datetime | None

class GateStatusReport(BaseModel):
    entries: list[GateStatusEntry]
    total_metrics: int
    passing: int
    blocked: int
    unknown: int                 # metrics with no DQ score yet
    gate_threshold: float
    generated_at: datetime
```

---

### 3. DQ Gate Logic

The gate threshold comes from `DQConfig.ml_gate` (currently `0.90`).

**Gate decision per metric:**
1. Query `dq.dq_scores` for the **latest composite score** for that metric
   (most recent `run_id` for that `target_id`)
2. If score ≥ `ml_gate` → **PASS** → include in feature vector
3. If score < `ml_gate` → **BLOCK** → exclude, set `gated_out=True`
4. If no DQ score exists yet → **UNKNOWN** → include with warning
   (configurable: `gate_unknown=False` to block unknowns instead)

**Composite score query** (use this pattern):
```sql
SELECT target_id, AVG(score) AS composite_score
FROM dq.dq_scores
WHERE run_id = (
    SELECT run_id FROM dq.dq_runs ORDER BY started_at DESC LIMIT 1
)
GROUP BY target_id
```

---

### 4. `metrica/ml_bridge/exporter.py` — Dataset Export

A thin utility for exporting the feature matrix to files:

```python
def export_to_csv(matrix: FeatureMatrix, output_path: Path) -> Path:
    """Write feature matrix to CSV. Returns path written."""

def export_to_parquet(matrix: FeatureMatrix, output_path: Path) -> Path:
    """Write feature matrix to Parquet if pyarrow available, else raise."""

def export_summary(matrix: FeatureMatrix) -> str:
    """Return a human-readable summary string of the matrix."""
```

Keep `pyarrow` as **optional** — import it inside `export_to_parquet()` and raise
`ImportError` with a helpful message if not available. Don't add it to `pyproject.toml`.

---

### 5. `scripts/run_feature_store.py` — CLI Entry Point

```bash
# Show DQ gate status — which metrics pass/fail
python3 scripts/run_feature_store.py --gate-status

# Get features for a single customer
python3 scripts/run_feature_store.py --customer CUST-0001

# Export full training matrix to CSV
python3 scripts/run_feature_store.py --export-csv data/churn_features.csv

# Export without DQ gate (include all metrics regardless of score)
python3 scripts/run_feature_store.py --export-csv data/churn_features_raw.csv --no-gate

# Show summary stats of the feature matrix
python3 scripts/run_feature_store.py --summary
```

**Example `--gate-status` output:**
```
Metrica Feature Store — DQ Gate Status
=======================================
Gate threshold: 0.90  |  32 passing  |  3 blocked  |  15 unknown

BLOCKED metrics (DQ score < 0.90):
  ✗ monthly_charges      validity=0.980 timeliness=0.867  composite=0.887
  ✗ tenure_months        completeness=0.950               composite=0.872

PASSING metrics (32):
  ✓ support_calls_30d    composite=1.000
  ✓ contract_type        composite=0.998
  ... (truncated)

UNKNOWN metrics (no DQ score yet, 15):
  ? avg_monthly_minutes  (no DQ run recorded)
  ? data_usage_gb        (no DQ run recorded)
  ...
```

**Example `--customer` output:**
```
Feature Vector: CUST-0001
=========================
  tenure_months          ✗ GATED  (DQ score 0.872 < gate 0.90)
  monthly_charges        ✗ GATED  (DQ score 0.887 < gate 0.90)
  support_calls_30d      ✓  2
  contract_type_encoded  ✓  0
  num_lines              ?  1   (unknown DQ)
  ...
Served: 33/50 metrics  |  Gated: 2  |  Unknown: 15
```

---

### 6. `metrica/ml_bridge/__init__.py` — Clean Exports

Replace the empty stub with proper exports:
```python
from metrica.ml_bridge.feature_store import FeatureStore
from metrica.ml_bridge.models import (
    FeatureVector, FeatureMatrix, FeatureValue,
    FeatureRecord, GateStatusReport, GateStatusEntry,
)
from metrica.ml_bridge.exporter import export_to_csv, export_summary

__all__ = [
    "FeatureStore",
    "FeatureVector", "FeatureMatrix", "FeatureValue",
    "FeatureRecord", "GateStatusReport", "GateStatusEntry",
    "export_to_csv", "export_summary",
]
```

---

### 7. `tests/test_feature_store.py` — Tests

```python
def test_gate_status_returns_report():
    """gate_status() returns GateStatusReport with correct totals."""

def test_passed_metrics_above_threshold():
    """passed_metrics() only returns metrics with DQ score >= ml_gate."""

def test_blocked_metrics_below_threshold():
    """blocked_metrics() returns metrics with DQ score < ml_gate.
    (mock data has WARNs on monthly_charges and tenure_months — these should be blocked
     if their composite score is below 0.90)."""

def test_get_features_single_customer():
    """get_features('CUST-0001') returns FeatureVector with expected fields."""

def test_get_features_gated_out():
    """Gated metrics have gated_out=True and value=None in FeatureVector."""

def test_get_feature_matrix_all_customers():
    """get_feature_matrix() returns FeatureMatrix with 1000 records."""

def test_feature_matrix_columns_match_passed_metrics():
    """FeatureMatrix.metrics_served == passed_metrics() list."""

def test_feature_matrix_no_gate():
    """enforce_dq_gate=False includes all metrics regardless of score."""

def test_export_to_csv(tmp_path):
    """export_to_csv() writes a valid CSV with correct columns and row count."""

def test_export_summary_string():
    """export_summary() returns a non-empty string with key stats."""

def test_unknown_metrics_handled():
    """Metrics with no DQ score are included with dq_status='unknown'."""

def test_selective_metrics():
    """get_feature_matrix(metric_ids=['tenure_months', 'monthly_charges'])
    returns matrix with only those 2 columns."""
```

---

## Acceptance Criteria

- [ ] `python3 scripts/run_feature_store.py --gate-status` runs and shows pass/block/unknown counts
- [ ] `python3 scripts/run_feature_store.py --customer CUST-0001` shows feature vector with gate indicators
- [ ] `python3 scripts/run_feature_store.py --export-csv data/churn_features.csv` writes valid CSV
- [ ] `python3 scripts/run_feature_store.py --summary` prints matrix stats
- [ ] `FeatureStore.get_feature_matrix()` returns all 1000 customers
- [ ] DQ gate correctly blocks metrics with composite score < 0.90
- [ ] Metrics with no DQ score are handled gracefully (not a crash)
- [ ] `metrica/ml_bridge/__init__.py` exports FeatureStore and all models cleanly
- [ ] `data/churn_features.csv` excluded from `.gitignore`
- [ ] All 12 new tests pass
- [ ] All 32 existing tests still pass — zero regressions
- [ ] Run `pytest tests/ -v` at the end and confirm total count

## Technical Notes

- **Run the DQ pipeline first** before testing: `python3 scripts/run_dq_checks.py` to ensure
  `dq.dq_scores` has fresh scores. Then `python3 scripts/run_pipeline.py` to ensure
  `metrics.customer_metrics` is populated. Both must run successfully before the feature
  store tests will work.
- The mock data has **injected DQ issues** that cause WARNs on `monthly_charges` (validity
  0.980, timeliness 0.867) and `tenure_months` (completeness 0.950, validity 0.990).
  Their composite scores should be below 0.90, making them perfect candidates for the
  DQ gate to block — use this in the tests.
- Most of the 50 metrics have **no DQ scores yet** (only 3 metrics have executable checks).
  The feature store must handle this gracefully — `dq_status='unknown'`, included by default.
- `FeatureMatrix.records` should be a list of `FeatureRecord` objects — do NOT load the
  entire `customer_metrics` table into Python memory as a DataFrame if avoidable.
  Use DuckDB's native query results and build records incrementally.
- For the CSV export, columns should be: `customer_id`, then one column per
  `metric_id` in `metrics_served`, then `_gated_metrics` as a JSON string column.
- Keep `FeatureStore` importable without side effects — no DB connection at import time,
  only in method calls.
- Add `data/churn_features*.csv` and `data/churn_features*.parquet` to `.gitignore`.


---
## Agent Response (2026-04-06 02:55:52)
**Outcome**: completed

Story 5.1 — Feature Store Interface + DQ Gate: FeatureStore class with DQ-gated feature retrieval, 6 Pydantic models, CSV export, CLI with --gate-status/--customer/--export-csv/--no-gate/--summary, 12 tests (44 total passing)
