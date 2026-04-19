# Task: Epic 6 Kickoff — Stories 6.1 + 6.2 — Churn Model Baseline

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-06
**Epic**: 6 — Churn Prediction (First ML Use Case)
**Stories**: 6.1 Feature Matrix Assembly + 6.2 Baseline Churn Model
**Priority**: High — this is the payoff for the entire Metrica stack
**Depends on**: Stories 1.3 ✅, 4.1 ✅, 5.1 ✅ — all complete

---

## Context & Where We Are

This is the moment the entire Metrica project has been building toward.
The full infrastructure stack is complete:

```
metrica/
├── registry/        50 metric YAMLs, 35 CDEs, 6 sources           ✅
├── dq/              5-dimension scoring, DuckDB store               ✅
├── monitoring/      DQScheduler, alerting, cron-ready              ✅
├── pipeline/        ETL: raw.* → metrics.customer_metrics           ✅
└── ml_bridge/       FeatureStore with DQ gate, CSV export           ✅

data/metrica_mock.duckdb
  raw.*               1000 customers, billing, ~1555 contact events
  metrics.*           customer_metrics populated by pipeline
  dq.*                scores for 3 metrics (11 checks)
  pipeline.*          pipeline_runs history

44 tests passing. All scripts operational.
```

**What's missing**: the churn label and the model itself.

This task delivers both:
1. **Story 6.1** — Add churn target variable to mock data + feature matrix assembly
2. **Story 6.2** — Baseline logistic regression model with full evaluation

---

## Story 6.1 — Churn Target Variable + Feature Matrix

### Churn Label Definition

Add a `churn_label_30d` column to `raw.crm_customers` and `metrics.customer_metrics`.

**Definition**: A customer is marked as churned (`1`) if their `account_status` is
`'Terminated'` in the mock data. Non-churned (`0`) if `'Active'` or `'Suspended'`.

This is a simplification for mock data — in production, churn would be derived from
status transitions with a 30-day observation window. Document this clearly in code comments.

```python
# In generate_mock_data.py — add to the customer generation:
# churn_label_30d: 1 if account_status == 'Terminated' else 0
# Expected distribution: ~5% churn (50 customers) — matches the 5% termination rate
```

**Update `generate_mock_data.py`** to:
1. Add `churn_label_30d INTEGER` column to `raw.crm_customers`
2. Populate: `1` if `account_status == 'Terminated'`, else `0`
3. Add `churn_label_30d INTEGER` column to `metrics.customer_metrics`
4. Populate from `raw.crm_customers.churn_label_30d`

**Add `churn_label_30d` to metric registry** — create
`definitions/metrics/churn_label_30d.yaml`:

```yaml
metric_id: churn_label_30d
name: "30-Day Churn Label"
description: >
  Binary churn indicator: 1 if customer churned within 30 days of observation date,
  0 otherwise. Derived from account_status transitions. Used as the target variable
  for churn prediction models.
  NOTE: In mock data, approximated as account_status == 'Terminated'.
domain: derived_engineered
owner: "data-science"
refresh_cadence: daily
data_type: integer
unit: binary_flag
source_mappings:
  - source_id: crm
    source_table: raw.crm_customers
    transformation_sql: |
      SELECT customer_id,
             CASE WHEN account_status = 'Terminated' THEN 1 ELSE 0 END
             AS churn_label_30d
      FROM raw.crm_customers
lineage:
  upstream_cdes:
    - crm.account_status
  downstream_consumers:
    - ml.churn_model_baseline
    - ml.churn_model_xgboost
dq_rules:
  - rule_id: churn_label_completeness
    name: "All customers have a churn label"
    dimension: completeness
    check_expression: |
      SELECT 1.0 - (COUNT(*) FILTER (WHERE churn_label_30d IS NULL)::FLOAT / COUNT(*))
      FROM metrics.customer_metrics
    warn_threshold: 1.0
    fail_threshold: 0.99
  - rule_id: churn_label_validity
    name: "Churn label is binary (0 or 1 only)"
    dimension: validity
    check_expression: |
      SELECT 1.0 - (COUNT(*) FILTER (
        WHERE churn_label_30d NOT IN (0, 1))::FLOAT / NULLIF(COUNT(*),0))
      FROM metrics.customer_metrics
    warn_threshold: 1.0
    fail_threshold: 1.0
tags:
  - target_variable
  - churn_prediction
  - ml_ready
version: "1.0"
status: active
```

### Feature Matrix Assembly

Before training, assemble the feature matrix using `FeatureStore`:

```python
from metrica.ml_bridge import FeatureStore
from pathlib import Path

fs = FeatureStore(
    db_path=Path("data/metrica_mock.duckdb"),
    definitions_root=Path("definitions/"),
)

# Export with DQ gate enforced
matrix = fs.get_feature_matrix(enforce_dq_gate=True)
```

The feature matrix should **exclude** `churn_label_30d` from features
(it's the target, not a predictor). Pull the label separately:

```python
# Features: all passed metrics EXCEPT churn_label_30d
feature_metric_ids = [m for m in fs.passed_metrics() if m != "churn_label_30d"]

# Labels: pulled directly from DB
# SELECT customer_id, churn_label_30d FROM metrics.customer_metrics
```

---

## Story 6.2 — Baseline Logistic Regression Model

### New Package: `metrica/ml/`

```
metrica/ml/
├── __init__.py
├── dataset.py       ← feature matrix → sklearn-ready X, y arrays
├── trainer.py       ← model training + evaluation
└── models.py        ← Pydantic models for model run results
```

### `metrica/ml/models.py` — Model Run Models

```python
from pydantic import BaseModel, Field
from datetime import datetime

class FeatureImportance(BaseModel):
    metric_id: str
    coefficient: float          # logistic regression coefficient
    abs_importance: float       # abs(coefficient) — for ranking
    rank: int                   # 1 = most important

class ModelEvaluation(BaseModel):
    auc_roc: float
    avg_precision: float        # area under precision-recall curve
    accuracy: float
    precision: float            # at default 0.5 threshold
    recall: float
    f1_score: float
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    support_positive: int       # total actual positives
    support_negative: int       # total actual negatives
    threshold_used: float = 0.5

class ModelRunResult(BaseModel):
    run_id: str                 # e.g. "model-run-<uuid4 short>"
    model_type: str             # "logistic_regression"
    trained_at: datetime
    training_customers: int
    test_customers: int
    features_used: list[str]    # metric_ids that went into X
    features_gated: list[str]   # metric_ids blocked by DQ gate
    churn_rate_train: float     # % positive in training set
    churn_rate_test: float      # % positive in test set
    evaluation: ModelEvaluation
    feature_importances: list[FeatureImportance]
    dq_gate_threshold: float
    notes: str = ""
```

### `metrica/ml/dataset.py` — Data Preparation

```python
import duckdb
import numpy as np
from pathlib import Path
from metrica.ml_bridge import FeatureStore

class ChurnDataset:
    def __init__(self, db_path: Path, definitions_root: Path):
        self.db_path = db_path
        self.definitions_root = definitions_root
        self.fs = FeatureStore(db_path, definitions_root)

    def build(
        self,
        exclude_metrics: list[str] | None = None,
        enforce_dq_gate: bool = True,
    ) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
        """
        Returns: (X, y, feature_names, gated_metrics)

        X: float32 array shape (n_customers, n_features)
           NULL values imputed with column median
        y: int array shape (n_customers,) — churn labels
        feature_names: list of metric_ids corresponding to X columns
        gated_metrics: metric_ids excluded by DQ gate
        """
```

**Data preparation rules:**
- Exclude `churn_label_30d` from X (it's y)
- Exclude any metrics with `status != 'active'` in the registry
- **NULL imputation**: fill NULLs with column median (simple, robust)
- **Boolean → int**: `True=1`, `False=0`
- **Type casting**: all features to `float32`
- **Row alignment**: X and y must have identical customer ordering
- Do NOT drop customers with NULL features — impute instead
- Log how many NULLs were imputed per feature

### `metrica/ml/trainer.py` — Model Training + Evaluation

```python
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    roc_auc_score, average_precision_score,
    accuracy_score, precision_score, recall_score,
    f1_score, confusion_matrix
)

class ChurnModelTrainer:
    def __init__(self, db_path: Path, definitions_root: Path, random_state: int = 42):
        ...

    def train_baseline(
        self,
        test_size: float = 0.2,
        enforce_dq_gate: bool = True,
        max_iter: int = 1000,
    ) -> ModelRunResult:
        """
        Full training pipeline:
        1. Build dataset via ChurnDataset
        2. Train/test split (stratified on y, random_state=42)
        3. StandardScaler fit on train, transform both
        4. LogisticRegression(max_iter=1000, random_state=42, class_weight='balanced')
        5. Evaluate on test set
        6. Build feature importances from model.coef_
        7. Persist result to ml.model_runs
        8. Return ModelRunResult
        """

    def _persist_result(self, result: ModelRunResult, conn): ...
    def _ensure_ml_schema(self, conn): ...
```

**Training notes:**
- Use `class_weight='balanced'` — mock data has ~5% churn (imbalanced)
- Use `StandardScaler` — logistic regression needs scaled features
- Stratified split — preserve churn rate in both train and test sets
- `random_state=42` everywhere for reproducibility
- `max_iter=1000` — some feature sets need more iterations to converge

**ML schema** — add `sql/004_ml_schema.sql`:
```sql
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.model_runs (
    run_id              VARCHAR PRIMARY KEY,
    model_type          VARCHAR NOT NULL,
    trained_at          TIMESTAMP NOT NULL,
    training_customers  INTEGER NOT NULL,
    test_customers      INTEGER NOT NULL,
    features_used_json  VARCHAR NOT NULL,   -- JSON list
    features_gated_json VARCHAR NOT NULL,   -- JSON list
    churn_rate_train    DOUBLE NOT NULL,
    churn_rate_test     DOUBLE NOT NULL,
    auc_roc             DOUBLE NOT NULL,
    avg_precision       DOUBLE NOT NULL,
    accuracy            DOUBLE NOT NULL,
    precision_score     DOUBLE NOT NULL,
    recall_score        DOUBLE NOT NULL,
    f1_score            DOUBLE NOT NULL,
    dq_gate_threshold   DOUBLE NOT NULL,
    evaluation_json     VARCHAR NOT NULL,   -- full ModelEvaluation as JSON
    importances_json    VARCHAR NOT NULL,   -- full list[FeatureImportance] as JSON
    notes               VARCHAR DEFAULT ''
);
```

### `scripts/run_churn_model.py` — CLI Entry Point

```bash
# Train baseline model with DQ gate enforced
python3 scripts/run_churn_model.py --train

# Train without DQ gate (use all metrics)
python3 scripts/run_churn_model.py --train --no-gate

# Show results of last model run
python3 scripts/run_churn_model.py --results

# Show feature importances from last run
python3 scripts/run_churn_model.py --importances
```

**Example `--train` output:**
```
Metrica Churn Model — Baseline Training
========================================
Building feature matrix...
  Metrics available:  50
  Metrics passed DQ gate: 33
  Metrics gated out:   2  (monthly_charges, tenure_months)
  Metrics unknown DQ: 15  (included)
  Features in X:      32  (churn_label_30d excluded as target)

Dataset: 1000 customers | 5.0% churn rate
Split: 800 train / 200 test (stratified)
NULL imputation: 47 values filled (median)

Training LogisticRegression(class_weight='balanced', max_iter=1000)...

── Evaluation (test set, n=200) ─────────────────────────────────
  AUC-ROC:          0.847
  Avg Precision:    0.412
  Accuracy:         0.785
  Precision:        0.231  (at threshold 0.50)
  Recall:           0.800
  F1 Score:         0.358

Confusion Matrix:
              Predicted 0   Predicted 1
  Actual 0        149            41
  Actual 1          2             8

── Top 10 Feature Importances ──────────────────────────────────
   1. support_calls_30d         +1.842
   2. contract_type_encoded     -1.203
   3. num_lines                 -0.987
   4. monthly_charges           +0.734   [GATED — shown for reference]
   5. device_financing_active   -0.651
   ...

Run ID: model-run-a3f9c1
Persisted to ml.model_runs ✅
```

---

## Dependencies to Install

```bash
# In the project venv:
pip install scikit-learn
```

Add `scikit-learn>=1.3` to `pyproject.toml` dependencies.

---

## Tests — `tests/test_churn_model.py`

```python
def test_churn_dataset_builds():
    """ChurnDataset.build() returns X, y, feature_names, gated_metrics."""

def test_churn_dataset_shape():
    """X has shape (1000, n_features), y has shape (1000,)."""

def test_churn_label_in_y_not_x():
    """churn_label_30d not in feature_names, is present in y."""

def test_churn_rate_approx_5pct():
    """y.mean() is approximately 0.05 (5% churn in mock data)."""

def test_no_nulls_in_X():
    """After imputation, X has no NaN values."""

def test_trainer_baseline_runs():
    """train_baseline() returns ModelRunResult with valid fields."""

def test_auc_roc_above_chance():
    """AUC-ROC > 0.5 (better than random on mock data)."""

def test_model_run_persisted():
    """ml.model_runs has a row after train_baseline()."""

def test_feature_importances_ranked():
    """feature_importances sorted by abs_importance desc, ranks sequential."""

def test_churn_label_yaml_loads():
    """definitions/metrics/churn_label_30d.yaml loads via DefinitionLoader."""

def test_mock_data_has_churn_column():
    """raw.crm_customers and metrics.customer_metrics both have churn_label_30d."""
```

---

## Acceptance Criteria

- [ ] `python3 scripts/generate_mock_data.py` (re-run) adds `churn_label_30d` to both tables
- [ ] `definitions/metrics/churn_label_30d.yaml` exists and loads cleanly
- [ ] `python3 scripts/run_churn_model.py --train` completes, prints evaluation, persists to DB
- [ ] `python3 scripts/run_churn_model.py --train --no-gate` runs with all metrics
- [ ] `python3 scripts/run_churn_model.py --results` shows last run's evaluation
- [ ] `python3 scripts/run_churn_model.py --importances` shows ranked feature coefficients
- [ ] AUC-ROC > 0.5 (model learns something from the mock data)
- [ ] `ml.model_runs` table created and populated after training
- [ ] `sql/004_ml_schema.sql` exists with ml schema DDL
- [ ] `scikit-learn>=1.3` added to `pyproject.toml`
- [ ] `metrica/ml/` package created with `dataset.py`, `trainer.py`, `models.py`
- [ ] All 11 new tests pass
- [ ] All 44 existing tests still pass — zero regressions
- [ ] Run `pytest tests/ -v` at end and confirm total count

## Technical Notes

- **Run order before training**: `generate_mock_data.py` → `run_pipeline.py` →
  `run_dq_checks.py` → `run_churn_model.py --train`. Each step feeds the next.
- With ~5% churn rate and mock data, expect AUC-ROC in the 0.6–0.85 range depending
  on which features have signal. The data is random-seeded so results are reproducible.
- `class_weight='balanced'` is critical — without it, the model predicts all-0 and
  gets 95% accuracy but 0% recall. We care about catching churners.
- The **confusion matrix** tells the real story for churn: false negatives (missed
  churners) are more costly than false positives (unnecessary retention calls).
  Note this in the output.
- For features that were **DQ-gated**, still show their importances in `--importances`
  output (from a separate `--no-gate` model run internally, or simply note "GATED —
  not used in training"). This lets Alex see what the gated features *would have*
  contributed — informative for DQ prioritisation.
- `metrica/ml/` is a new top-level package — add `__init__.py` with clean exports.
- Keep `ChurnDataset` and `ChurnModelTrainer` importable without side effects.


---
## Agent Response (2026-04-06 03:25:35)
**Outcome**: completed

Epic 6 Stories 6.1+6.2: churn_label_30d target variable, baseline logistic regression with DQ-gated features, StandardScaler, class_weight=balanced, CLI with --train/--no-gate/--results/--importances, ml.model_runs persistence, 11 tests (55 total passing)
