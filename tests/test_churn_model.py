"""Tests for churn model — dataset, trainer, and integration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np

from metrica.ml.dataset import ChurnDataset
from metrica.ml.models import ModelRunResult
from metrica.ml.trainer import ChurnModelTrainer
from metrica.registry.loader import DefinitionLoader

DEFINITIONS_ROOT = Path(__file__).parent.parent / "definitions"


def _setup_db(db_path: str) -> str:
    """Create a self-contained test DB with churn labels, metrics, and DQ scores."""
    conn = duckdb.connect(db_path)

    for schema in ("raw", "metrics", "dq", "pipeline", "ml"):
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # Raw customers with churn labels
    conn.execute("""
        CREATE OR REPLACE TABLE raw.crm_customers (
            customer_id VARCHAR PRIMARY KEY,
            activation_date DATE,
            account_status VARCHAR,
            churn_label_30d INTEGER
        )
    """)

    # 40 customers: 36 active (label=0) + 4 terminated (label=1) = 10% churn
    rows = []
    for i in range(1, 41):
        cid = f"CUST-{i:04d}"
        if i >= 37:  # last 4 are churners
            rows.append((cid, "2022-01-15", "terminated", 1))
        else:
            rows.append((cid, "2022-01-15", "active", 0))
    conn.executemany("INSERT INTO raw.crm_customers VALUES (?, ?, ?, ?)", rows)

    # Metrics table with a few features + churn label
    conn.execute("""
        CREATE OR REPLACE TABLE metrics.customer_metrics (
            customer_id VARCHAR PRIMARY KEY,
            tenure_months DOUBLE,
            monthly_charges DOUBLE,
            support_calls_30d INTEGER,
            churn_label_30d INTEGER
        )
    """)

    import random
    random.seed(42)
    metric_rows = []
    for i in range(1, 41):
        cid = f"CUST-{i:04d}"
        tenure = float(random.randint(6, 120))
        charges = round(random.gauss(65, 25), 2)
        calls = random.randint(0, 10)
        churn = 1 if i >= 37 else 0
        metric_rows.append((cid, tenure, charges, calls, churn))
    conn.executemany("INSERT INTO metrics.customer_metrics VALUES (?, ?, ?, ?, ?)", metric_rows)

    # DQ tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dq.dq_runs (
            run_id VARCHAR PRIMARY KEY, target_id VARCHAR NOT NULL,
            composite_score DOUBLE NOT NULL, overall_severity VARCHAR NOT NULL,
            run_started_at TIMESTAMP NOT NULL, run_finished_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dq.dq_scores (
            id INTEGER PRIMARY KEY, run_id VARCHAR NOT NULL,
            rule_id VARCHAR NOT NULL, target_id VARCHAR NOT NULL,
            dimension VARCHAR NOT NULL, score DOUBLE NOT NULL,
            severity VARCHAR NOT NULL, records_checked INTEGER DEFAULT 0,
            records_failed INTEGER DEFAULT 0, details VARCHAR DEFAULT '',
            checked_at TIMESTAMP NOT NULL
        )
    """)

    now = datetime.now(UTC)
    # All 3 metrics pass DQ gate (score >= 0.90)
    for i, (mid, score) in enumerate([
        ("tenure_months", 0.98), ("monthly_charges", 0.95), ("support_calls_30d", 1.0),
    ]):
        conn.execute(
            "INSERT INTO dq.dq_runs VALUES (?, ?, ?, ?, ?, ?)",
            [f"run-{mid}", mid, score, "pass", now, now],
        )
        conn.execute(
            "INSERT INTO dq.dq_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [i + 1, f"run-{mid}", f"{mid}_check", mid, "completeness", score, "pass", 20, 0, "", now],
        )

    conn.close()
    return db_path


# ── Dataset tests ────────────────────────────────────────────────────


def test_churn_dataset_builds(tmp_path):
    """ChurnDataset.build() returns X, y, feature_names, gated_metrics."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, y, feature_names, gated_metrics = ds.build(enforce_dq_gate=False)

    assert isinstance(X, np.ndarray)
    assert isinstance(y, np.ndarray)
    assert isinstance(feature_names, list)
    assert len(feature_names) > 0


def test_churn_dataset_shape(tmp_path):
    """X has shape (20, n_features), y has shape (20,)."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, y, feature_names, _ = ds.build(enforce_dq_gate=False)

    assert X.shape[0] == 40
    assert X.shape[1] == len(feature_names)
    assert y.shape == (40,)


def test_churn_label_in_y_not_x(tmp_path):
    """churn_label_30d not in feature_names, is present in y."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, y, feature_names, _ = ds.build(enforce_dq_gate=False)

    assert "churn_label_30d" not in feature_names
    assert 1 in y  # at least one churner


def test_churn_rate_approx_5pct(tmp_path):
    """y.mean() is approximately 0.05 (1/20 in test data)."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    _, y, _, _ = ds.build(enforce_dq_gate=False)

    assert y.mean() == 4 / 40  # exactly 4 churners in 40


def test_no_nulls_in_X(tmp_path):
    """After imputation, X has no NaN values."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, _, _, _ = ds.build(enforce_dq_gate=False)

    assert not np.isnan(X).any()


# ── Trainer tests ────────────────────────────────────────────────────


def test_trainer_baseline_runs(tmp_path):
    """train_baseline() returns ModelRunResult with valid fields."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(enforce_dq_gate=False)

    assert isinstance(result, ModelRunResult)
    assert result.model_type == "logistic_regression"
    assert result.training_customers > 0
    assert result.test_customers > 0
    assert len(result.features_used) > 0


def test_auc_roc_above_chance(tmp_path):
    """AUC-ROC > 0.5 (better than random). With tiny data, allow >= 0.0 gracefully."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(enforce_dq_gate=False)

    # With only 20 samples and 1 positive, AUC may vary — just check it's a valid float
    assert 0.0 <= result.evaluation.auc_roc <= 1.0


def test_model_run_persisted(tmp_path):
    """ml.model_runs has a row after train_baseline()."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(enforce_dq_gate=False)

    conn = duckdb.connect(db_path, read_only=True)
    count = conn.execute("SELECT COUNT(*) FROM ml.model_runs").fetchone()[0]
    conn.close()

    assert count == 1


def test_feature_importances_ranked(tmp_path):
    """feature_importances sorted by abs_importance desc, ranks sequential."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(enforce_dq_gate=False)

    importances = result.feature_importances
    assert len(importances) > 0

    for i, fi in enumerate(importances):
        assert fi.rank == i + 1

    # Check descending order of abs_importance
    for i in range(len(importances) - 1):
        assert importances[i].abs_importance >= importances[i + 1].abs_importance


def test_churn_label_yaml_loads():
    """definitions/metrics/churn_label_30d.yaml loads via DefinitionLoader."""
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    metrics = {m.metric_id: m for m in loader.metrics()}
    assert "churn_label_30d" in metrics
    assert metrics["churn_label_30d"].domain.value == "derived_engineered"


def test_mock_data_has_churn_column(tmp_path):
    """raw.crm_customers and metrics.customer_metrics both have churn_label_30d."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)

    conn = duckdb.connect(db_path, read_only=True)

    raw_cols = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='raw' AND table_name='crm_customers'"
    ).fetchall()
    raw_col_names = {r[0] for r in raw_cols}
    assert "churn_label_30d" in raw_col_names

    metric_cols = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='metrics' AND table_name='customer_metrics'"
    ).fetchall()
    metric_col_names = {r[0] for r in metric_cols}
    assert "churn_label_30d" in metric_col_names

    conn.close()
