"""Tests for the ML Feature Store — DQ-gated feature serving."""

from __future__ import annotations

import csv
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from metrica.ml_bridge.feature_store import FeatureStore
from metrica.ml_bridge.exporter import export_to_csv, export_summary
from metrica.ml_bridge.models import (
    FeatureMatrix,
    FeatureVector,
    GateStatusReport,
)

DEFINITIONS_ROOT = Path(__file__).parent.parent / "definitions"


def _setup_db(db_path: str) -> duckdb.DuckDBPyConnection:
    """Create schemas, insert 3 test customers and DQ scores."""
    conn = duckdb.connect(db_path)

    # Create schemas
    for schema in ("raw", "metrics", "dq", "pipeline"):
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # Create raw tables (needed for metric SQL references)
    conn.execute("""
        CREATE OR REPLACE TABLE raw.crm_customers (
            customer_id VARCHAR PRIMARY KEY,
            activation_date DATE,
            account_status VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO raw.crm_customers VALUES
        ('CUST-0001', '2022-01-15', 'active'),
        ('CUST-0002', '2023-06-20', 'active'),
        ('CUST-0003', '2024-01-01', 'active')
    """)

    # Create metrics.customer_metrics with a few test columns
    conn.execute("""
        CREATE OR REPLACE TABLE metrics.customer_metrics (
            customer_id VARCHAR PRIMARY KEY,
            tenure_months DOUBLE,
            monthly_charges DOUBLE,
            support_calls_30d INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO metrics.customer_metrics VALUES
        ('CUST-0001', 48.0, 79.99, 2),
        ('CUST-0002', 18.0, 49.99, 0),
        ('CUST-0003', 12.0, 29.99, 5)
    """)

    # DQ tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dq.dq_runs (
            run_id          VARCHAR PRIMARY KEY,
            target_id       VARCHAR NOT NULL,
            composite_score DOUBLE NOT NULL,
            overall_severity VARCHAR NOT NULL,
            run_started_at  TIMESTAMP NOT NULL,
            run_finished_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dq.dq_scores (
            id              INTEGER PRIMARY KEY,
            run_id          VARCHAR NOT NULL,
            rule_id         VARCHAR NOT NULL,
            target_id       VARCHAR NOT NULL,
            dimension       VARCHAR NOT NULL,
            score           DOUBLE NOT NULL,
            severity        VARCHAR NOT NULL,
            records_checked INTEGER DEFAULT 0,
            records_failed  INTEGER DEFAULT 0,
            details         VARCHAR DEFAULT '',
            checked_at      TIMESTAMP NOT NULL
        )
    """)

    now = datetime.now(UTC)

    # tenure_months — composite 0.85 → BLOCKED
    conn.execute(
        "INSERT INTO dq.dq_runs VALUES (?, ?, ?, ?, ?, ?)",
        ["run-tenure", "tenure_months", 0.85, "warn", now, now],
    )
    conn.execute(
        "INSERT INTO dq.dq_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [1, "run-tenure", "tenure_completeness", "tenure_months", "completeness", 0.85, "warn", 100, 15, "", now],
    )

    # monthly_charges — composite 0.88 → BLOCKED
    conn.execute(
        "INSERT INTO dq.dq_runs VALUES (?, ?, ?, ?, ?, ?)",
        ["run-charges", "monthly_charges", 0.88, "warn", now, now],
    )
    conn.execute(
        "INSERT INTO dq.dq_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [2, "run-charges", "charges_validity", "monthly_charges", "validity", 0.88, "warn", 100, 12, "", now],
    )

    # support_calls_30d — composite 0.98 → PASS
    conn.execute(
        "INSERT INTO dq.dq_runs VALUES (?, ?, ?, ?, ?, ?)",
        ["run-support", "support_calls_30d", 0.98, "pass", now, now],
    )
    conn.execute(
        "INSERT INTO dq.dq_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [3, "run-support", "support_completeness", "support_calls_30d", "completeness", 0.98, "pass", 100, 2, "", now],
    )

    conn.close()
    return db_path


def _make_store(db_path: str) -> FeatureStore:
    return FeatureStore(Path(db_path), DEFINITIONS_ROOT)


# ── Gate status ──────────────────────────────────────────────────────


def test_gate_status_returns_report(tmp_path):
    """gate_status() returns GateStatusReport with correct totals."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    report = store.gate_status()
    assert isinstance(report, GateStatusReport)
    assert report.total_metrics == report.passing + report.blocked + report.unknown
    assert report.total_metrics > 0
    assert report.gate_threshold == 0.90


def test_passed_metrics_above_threshold(tmp_path):
    """passed_metrics() only returns metrics with DQ score >= ml_gate."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    passed = store.passed_metrics()
    assert "support_calls_30d" in passed
    # Blocked metrics should NOT be in passed
    assert "tenure_months" not in passed
    assert "monthly_charges" not in passed


def test_blocked_metrics_below_threshold(tmp_path):
    """blocked_metrics() returns metrics with DQ score < ml_gate."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    blocked = store.blocked_metrics()
    assert "tenure_months" in blocked
    assert "monthly_charges" in blocked
    assert "support_calls_30d" not in blocked


# ── Single customer features ────────────────────────────────────────


def test_get_features_single_customer(tmp_path):
    """get_features('CUST-0001') returns FeatureVector with expected fields."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    vector = store.get_features("CUST-0001")
    assert isinstance(vector, FeatureVector)
    assert vector.customer_id == "CUST-0001"
    assert vector.metrics_requested > 0
    assert vector.metrics_served <= vector.metrics_requested
    assert vector.dq_gate_threshold == 0.90

    # support_calls_30d should be served
    support = next((f for f in vector.features if f.metric_id == "support_calls_30d"), None)
    assert support is not None
    assert support.value == 2
    assert support.gated_out is False


def test_get_features_gated_out(tmp_path):
    """Gated metrics have gated_out=True and value=None in FeatureVector."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    vector = store.get_features("CUST-0001")
    tenure = next((f for f in vector.features if f.metric_id == "tenure_months"), None)
    assert tenure is not None
    assert tenure.gated_out is True
    assert tenure.value is None
    assert tenure.dq_score == 0.85


# ── Feature matrix ──────────────────────────────────────────────────


def test_get_feature_matrix_all_customers(tmp_path):
    """get_feature_matrix() returns FeatureMatrix with 3 records (our test data)."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    matrix = store.get_feature_matrix()
    assert isinstance(matrix, FeatureMatrix)
    assert matrix.total_customers == 3


def test_feature_matrix_columns_match_passed_metrics(tmp_path):
    """FeatureMatrix.metrics_served matches passed_metrics() ordering."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    matrix = store.get_feature_matrix()
    passed = store.passed_metrics()

    # metrics_served should be a subset of (or equal to) passed_metrics
    for mid in matrix.metrics_served:
        assert mid in passed


def test_feature_matrix_no_gate(tmp_path):
    """enforce_dq_gate=False includes all metrics regardless of score."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    matrix_gated = store.get_feature_matrix(enforce_dq_gate=True)
    matrix_ungated = store.get_feature_matrix(enforce_dq_gate=False)

    # Ungated should serve more or equal metrics
    assert len(matrix_ungated.metrics_served) >= len(matrix_gated.metrics_served)
    assert len(matrix_ungated.metrics_gated) == 0


# ── Export ───────────────────────────────────────────────────────────


def test_export_to_csv(tmp_path):
    """export_to_csv() writes a valid CSV with correct columns and row count."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    matrix = store.get_feature_matrix()
    csv_path = tmp_path / "features.csv"
    result_path = export_to_csv(matrix, csv_path)

    assert result_path.exists()
    with open(result_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    assert header[0] == "customer_id"
    assert len(rows) == 3  # 3 test customers


def test_export_summary_string(tmp_path):
    """export_summary() returns a non-empty string with key stats."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    matrix = store.get_feature_matrix()
    summary = export_summary(matrix)

    assert isinstance(summary, str)
    assert "Customers:" in summary
    assert "3" in summary  # 3 test customers


# ── Edge cases ───────────────────────────────────────────────────────


def test_unknown_metrics_handled(tmp_path):
    """Metrics with no DQ score are included with dq_status='unknown'."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    # Most of the 50 metrics have no DQ scores → should be unknown
    report = store.gate_status()
    assert report.unknown > 0

    # Unknown metrics should still pass the gate (included by default)
    vector = store.get_features("CUST-0001")
    unknown_features = [f for f in vector.features if f.dq_status == "unknown"]
    assert len(unknown_features) > 0
    for uf in unknown_features:
        assert uf.gated_out is False


def test_selective_metrics(tmp_path):
    """get_feature_matrix(metric_ids=[...]) returns matrix with only those columns."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    store = _make_store(db_path)

    # Request only 2 specific metrics (both blocked by DQ)
    matrix = store.get_feature_matrix(
        metric_ids=["tenure_months", "monthly_charges"],
        enforce_dq_gate=False,
    )
    assert matrix.total_metrics == 2
    assert set(matrix.metrics_served) == {"tenure_months", "monthly_charges"}

    # With gate ON, both should be blocked
    matrix_gated = store.get_feature_matrix(
        metric_ids=["tenure_months", "monthly_charges"],
        enforce_dq_gate=True,
    )
    assert len(matrix_gated.metrics_gated) == 2
    assert len(matrix_gated.metrics_served) == 0
