"""Tests for mock data generation and DQ runner."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

# Add scripts to path for imports
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

DB_PATH = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"


@pytest.fixture(scope="module", autouse=True)
def generate_data():
    """Run mock data generator once before all tests in this module."""
    from generate_mock_data import main as gen_main
    gen_main()
    yield
    # Cleanup not needed — DB can be regenerated


def _connect():
    return duckdb.connect(str(DB_PATH), read_only=True)


def test_mock_db_schema():
    """Verify all expected tables exist after generation."""
    conn = _connect()
    tables = conn.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('raw', 'metrics', 'dq')
        ORDER BY table_schema, table_name
    """).fetchall()
    conn.close()

    table_names = {f"{s}.{t}" for s, t in tables}
    assert "raw.crm_customers" in table_names
    assert "raw.billing_invoices" in table_names
    assert "raw.contact_center_interactions" in table_names
    assert "metrics.customer_metrics" in table_names
    assert "dq.dq_runs" in table_names
    assert "dq.dq_scores" in table_names


def test_customer_count():
    """Exactly 1,000 customers in raw.crm_customers."""
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM raw.crm_customers").fetchone()[0]
    conn.close()
    assert count == 1000


def test_metrics_computed():
    """metrics.customer_metrics has 1,000 rows, no all-null rows."""
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM metrics.customer_metrics").fetchone()[0]
    all_null = conn.execute("""
        SELECT COUNT(*) FROM metrics.customer_metrics
        WHERE tenure_months IS NULL AND monthly_charges IS NULL AND support_calls_30d IS NULL
    """).fetchone()[0]
    conn.close()
    assert count == 1000
    assert all_null == 0  # At least one column should be non-null per row


def test_dq_issues_null_activation_dates():
    """Verify injected NULL activation_dates exist."""
    conn = _connect()
    null_count = conn.execute(
        "SELECT COUNT(*) FROM raw.crm_customers WHERE activation_date IS NULL"
    ).fetchone()[0]
    conn.close()
    assert null_count == 50


def test_dq_issues_negative_charges():
    """Verify injected negative charges exist."""
    conn = _connect()
    neg_count = conn.execute(
        "SELECT COUNT(*) FROM raw.billing_invoices WHERE monthly_charge_amount < 0"
    ).fetchone()[0]
    conn.close()
    assert neg_count == 20


def test_dq_issues_future_dates():
    """Verify injected future activation dates exist."""
    conn = _connect()
    future_count = conn.execute(
        "SELECT COUNT(*) FROM raw.crm_customers WHERE activation_date > DATE '2026-12-31'"
    ).fetchone()[0]
    conn.close()
    assert future_count == 10


def test_dq_issues_duplicate_interactions():
    """Verify duplicate interaction IDs exist."""
    conn = _connect()
    dup_count = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT interaction_id, COUNT(*) AS cnt
            FROM raw.contact_center_interactions
            GROUP BY interaction_id
            HAVING cnt > 1
        )
    """).fetchone()[0]
    conn.close()
    assert dup_count >= 1


def test_dq_runner_produces_scores():
    """Run DQ checks and verify scores are persisted."""
    from run_dq_checks import run_dq_checks

    results = run_dq_checks(db_path=DB_PATH)

    # Should have results for all 3 metrics
    metric_ids = {r["metric_id"] for r in results}
    assert "tenure_months" in metric_ids
    assert "monthly_charges" in metric_ids
    assert "support_calls_30d" in metric_ids

    # All scores should be between 0 and 1
    for r in results:
        assert 0.0 <= r["score"] <= 1.0

    # Verify scores are persisted in DB
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    score_count = conn.execute("SELECT COUNT(*) FROM dq.dq_scores").fetchone()[0]
    run_count = conn.execute("SELECT COUNT(*) FROM dq.dq_runs").fetchone()[0]
    conn.close()

    assert score_count > 0
    assert run_count > 0
