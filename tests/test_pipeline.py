"""Tests for the ETL pipeline — transformer and runner."""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

from metrica.pipeline.models import PipelineStatus
from metrica.pipeline.runner import PipelineRunner
from metrica.pipeline.transformer import MetricTransformer
from metrica.registry.loader import DefinitionLoader

DEFINITIONS_ROOT = Path(__file__).parent.parent / "definitions"


def _setup_db(conn: duckdb.DuckDBPyConnection):
    """Create raw/metrics schemas and insert minimal test data."""
    conn.execute("CREATE SCHEMA IF NOT EXISTS raw")
    conn.execute("CREATE SCHEMA IF NOT EXISTS metrics")

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
        ('CUST-0003', NULL, 'active')
    """)

    conn.execute("""
        CREATE OR REPLACE TABLE raw.billing_invoices (
            invoice_id VARCHAR PRIMARY KEY,
            customer_id VARCHAR,
            monthly_charge_amount DOUBLE,
            invoice_date DATE
        )
    """)
    conn.execute("""
        INSERT INTO raw.billing_invoices VALUES
        ('INV-001', 'CUST-0001', 79.99, CURRENT_DATE),
        ('INV-002', 'CUST-0002', 49.99, CURRENT_DATE),
        ('INV-003', 'CUST-0001', 69.99, CURRENT_DATE - INTERVAL '30 days')
    """)

    conn.execute("""
        CREATE OR REPLACE TABLE raw.contact_center_interactions (
            interaction_id VARCHAR PRIMARY KEY,
            customer_id VARCHAR,
            interaction_date DATE,
            interaction_type VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO raw.contact_center_interactions VALUES
        ('INT-001', 'CUST-0001', CURRENT_DATE, 'call'),
        ('INT-002', 'CUST-0001', CURRENT_DATE - INTERVAL '5 days', 'call'),
        ('INT-003', 'CUST-0002', CURRENT_DATE - INTERVAL '60 days', 'call'),
        ('INT-004', 'CUST-0002', CURRENT_DATE, 'chat')
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS metrics.customer_metrics (
            customer_id       VARCHAR PRIMARY KEY,
            tenure_months     INTEGER,
            monthly_charges   DOUBLE,
            support_calls_30d INTEGER,
            last_updated      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


# --- Transformer tests ---


def test_transformer_expression_metric():
    """tenure_months uses an expression-only transformation."""
    conn = duckdb.connect(":memory:")
    _setup_db(conn)
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    metric = [m for m in loader.metrics() if m.metric_id == "tenure_months"][0]

    t = MetricTransformer(conn)
    result = t.transform(metric)

    assert result.status == PipelineStatus.SUCCESS
    assert result.rows_written >= 2  # at least the 2 non-null activation dates
    conn.close()


def test_transformer_select_metric():
    """monthly_charges uses a full SELECT transformation."""
    conn = duckdb.connect(":memory:")
    _setup_db(conn)
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    metric = [m for m in loader.metrics() if m.metric_id == "monthly_charges"][0]

    t = MetricTransformer(conn)
    result = t.transform(metric)

    assert result.status == PipelineStatus.SUCCESS
    assert result.rows_written == 2  # 2 customers with invoices

    row = conn.execute(
        "SELECT monthly_charges FROM metrics.customer_metrics WHERE customer_id = 'CUST-0001'"
    ).fetchone()
    assert row is not None
    assert row[0] == 79.99  # latest invoice only
    conn.close()


# --- Runner tests (use temp DB file) ---


def _make_runner_db() -> tuple[Path, Path]:
    """Create a temp DB with mock data, return (db_path, tmp_dir)."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.duckdb"
    conn = duckdb.connect(str(db_path))
    _setup_db(conn)
    conn.close()
    return db_path, Path(tmp)


PILOT_METRICS = ["tenure_months", "monthly_charges", "support_calls_30d"]


def test_runner_all_metrics():
    db_path, _ = _make_runner_db()
    runner = PipelineRunner(db_path, DEFINITIONS_ROOT)
    result = runner.run(metric_ids=PILOT_METRICS)

    assert result.metrics_attempted == 3
    assert result.metrics_succeeded == 3
    assert result.status == PipelineStatus.SUCCESS


def test_runner_all_50_metrics_attempted():
    """Running all metrics shows 50 attempted, 3 succeed (pilot), rest fail (no mock tables)."""
    db_path, _ = _make_runner_db()
    runner = PipelineRunner(db_path, DEFINITIONS_ROOT)
    result = runner.run()

    assert result.metrics_attempted == 51
    assert result.metrics_succeeded == 3
    assert result.status == PipelineStatus.PARTIAL


def test_runner_rows_written():
    db_path, _ = _make_runner_db()
    runner = PipelineRunner(db_path, DEFINITIONS_ROOT)
    result = runner.run(metric_ids=PILOT_METRICS)

    assert result.total_rows_written > 0

    conn = duckdb.connect(str(db_path))
    rows = conn.execute("SELECT COUNT(*) FROM metrics.customer_metrics").fetchone()
    assert rows[0] >= 2
    conn.close()


def test_runner_dry_run():
    db_path, _ = _make_runner_db()
    runner = PipelineRunner(db_path, DEFINITIONS_ROOT)
    result = runner.run(metric_ids=PILOT_METRICS, dry_run=True)

    assert result.metrics_attempted == 3
    assert result.total_rows_written == 0
    assert result.status == PipelineStatus.SUCCESS

    conn = duckdb.connect(str(db_path))
    rows = conn.execute("SELECT COUNT(*) FROM metrics.customer_metrics").fetchone()
    assert rows[0] == 0  # nothing written
    conn.close()


def test_runner_selective():
    db_path, _ = _make_runner_db()
    runner = PipelineRunner(db_path, DEFINITIONS_ROOT)
    result = runner.run(metric_ids=["monthly_charges"])

    assert result.metrics_attempted == 1
    assert result.metrics_succeeded == 1


def test_runner_run_persisted():
    db_path, _ = _make_runner_db()
    runner = PipelineRunner(db_path, DEFINITIONS_ROOT)
    result = runner.run(metric_ids=PILOT_METRICS)

    conn = duckdb.connect(str(db_path))
    rows = conn.execute("SELECT * FROM pipeline.pipeline_runs").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == result.run_id  # run_id matches
    conn.close()


def test_runner_idempotent():
    db_path, _ = _make_runner_db()
    runner = PipelineRunner(db_path, DEFINITIONS_ROOT)

    r1 = runner.run(metric_ids=PILOT_METRICS)
    r2 = runner.run(metric_ids=PILOT_METRICS)

    assert r1.status == PipelineStatus.SUCCESS
    assert r2.status == PipelineStatus.SUCCESS

    conn = duckdb.connect(str(db_path))
    runs = conn.execute("SELECT COUNT(*) FROM pipeline.pipeline_runs").fetchone()
    assert runs[0] == 2  # two separate runs persisted

    # customer_metrics shouldn't have duplicates — upsert should overwrite
    custs = conn.execute("SELECT COUNT(*) FROM metrics.customer_metrics").fetchone()
    assert custs[0] <= 3  # max 3 customers from test data
    conn.close()


def test_transformer_partial_failure():
    """A metric with a bad transformation should fail gracefully."""
    conn = duckdb.connect(":memory:")
    _setup_db(conn)

    from metrica.registry.models import MetricDefinition, SourceMapping

    bad_metric = MetricDefinition(
        metric_id="broken_metric",
        name="Broken",
        domain="billing_financial",
        owner="test",
        refresh_cadence="daily",
        data_type="integer",
        source_mappings=[
            SourceMapping(
                source_system="crm",
                source_table="nonexistent_table",
                source_fields=["x"],
                transformation="SELECT customer_id, 1 AS broken_metric FROM nonexistent_table",
            )
        ],
    )

    t = MetricTransformer(conn)
    result = t.transform(bad_metric)

    assert result.status == PipelineStatus.FAILED
    assert result.error is not None
    conn.close()
