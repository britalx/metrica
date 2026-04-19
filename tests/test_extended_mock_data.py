"""Tests for extended mock data (CDR, Network, App tables and churn correlation)."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

DB_PATH = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"


@pytest.fixture(scope="module", autouse=True)
def generate_data():
    """Run mock data generator once before all tests in this module."""
    from generate_mock_data import main as gen_main
    gen_main()


def _connect():
    return duckdb.connect(str(DB_PATH), read_only=True)


# ── Table existence & row counts ───────────────────────────

class TestNewTables:
    def test_cdr_table_exists_and_populated(self):
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM raw.cdr_call_records").fetchone()[0]
        conn.close()
        assert count > 10_000, f"Expected >10K CDR rows, got {count}"

    def test_network_table_exists_and_populated(self):
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM raw.network_measurements").fetchone()[0]
        conn.close()
        assert count > 20_000, f"Expected >20K network rows, got {count}"

    def test_app_events_table_exists_and_populated(self):
        conn = _connect()
        count = conn.execute("SELECT COUNT(*) FROM raw.app_events").fetchone()[0]
        conn.close()
        assert count > 5_000, f"Expected >5K app event rows, got {count}"


# ── Churn correlation ──────────────────────────────────────

class TestChurnCorrelation:
    def test_churn_customers_lower_usage(self):
        """Churned customers should have lower avg_monthly_minutes."""
        conn = _connect()
        result = conn.execute("""
            SELECT churn_label_30d, AVG(avg_monthly_minutes)
            FROM metrics.customer_metrics
            WHERE avg_monthly_minutes IS NOT NULL
            GROUP BY churn_label_30d
            ORDER BY churn_label_30d
        """).fetchall()
        conn.close()
        active_avg = result[0][1]
        churned_avg = result[1][1]
        assert churned_avg < active_avg, (
            f"Churned avg_monthly_minutes ({churned_avg}) should be < active ({active_avg})"
        )

    def test_churn_customers_worse_signal(self):
        """Churned customers should have weaker signal strength."""
        conn = _connect()
        result = conn.execute("""
            SELECT churn_label_30d, AVG(avg_signal_strength_home)
            FROM metrics.customer_metrics
            WHERE avg_signal_strength_home IS NOT NULL
            GROUP BY churn_label_30d
            ORDER BY churn_label_30d
        """).fetchall()
        conn.close()
        active_signal = result[0][1]
        churned_signal = result[1][1]
        # More negative = weaker signal
        assert churned_signal < active_signal, (
            f"Churned signal ({churned_signal}) should be weaker (more negative) than active ({active_signal})"
        )

    def test_churn_customers_fewer_logins(self):
        """Churned customers should have lower login frequency."""
        conn = _connect()
        result = conn.execute("""
            SELECT churn_label_30d, AVG(login_app_frequency)
            FROM metrics.customer_metrics
            WHERE login_app_frequency IS NOT NULL
            GROUP BY churn_label_30d
            ORDER BY churn_label_30d
        """).fetchall()
        conn.close()
        active_logins = result[0][1]
        churned_logins = result[1][1]
        assert churned_logins < active_logins, (
            f"Churned login freq ({churned_logins}) should be < active ({active_logins})"
        )


# ── Metric columns ────────────────────────────────────────

class TestMetricColumns:
    NEW_COLUMNS = [
        "avg_monthly_minutes", "calls_per_day", "data_usage_gb", "sms_count",
        "roaming_usage", "night_weekend_usage_ratio", "usage_trend_3m",
        "dropped_call_rate", "avg_signal_strength_home", "outage_events_experienced",
        "data_throttling_events", "speed_test_avg_mbps", "login_app_frequency",
        "days_since_last_login", "usage_vs_plan_utilization",
    ]

    def test_customer_metrics_has_new_columns(self):
        """All 15 new metric columns should exist in customer_metrics."""
        conn = _connect()
        cols = conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'metrics' AND table_name = 'customer_metrics'
        """).fetchall()
        conn.close()
        col_names = {r[0] for r in cols}
        for col in self.NEW_COLUMNS:
            assert col in col_names, f"Missing column: {col}"

    def test_new_columns_populated(self):
        """New columns should have non-null values for the majority of rows."""
        conn = _connect()
        for col in ["avg_monthly_minutes", "avg_signal_strength_home", "data_usage_gb"]:
            non_null = conn.execute(
                f"SELECT COUNT(*) FROM metrics.customer_metrics WHERE {col} IS NOT NULL"
            ).fetchone()[0]
            assert non_null > 900, f"{col} has only {non_null} non-null values"
        conn.close()


# ── Pipeline integration ───────────────────────────────────

class TestPipelineIntegration:
    def test_pipeline_succeeds_on_cdr_metrics(self):
        """Pipeline should succeed on at least 12 metrics total."""
        from metrica.pipeline.runner import PipelineRunner
        runner = PipelineRunner(
            db_path=DB_PATH,
            definitions_root=Path(__file__).parent.parent / "definitions",
        )
        result = runner.run()
        assert result.metrics_succeeded >= 12, (
            f"Only {result.metrics_succeeded} metrics succeeded in pipeline, expected ≥12"
        )


# ── Model AUC ─────────────────────────────────────────────

class TestModelQuality:
    def test_auc_roc_above_threshold(self):
        """Model AUC-ROC should be ≥ 0.65 with extended features."""
        from metrica.ml.trainer import ChurnModelTrainer
        definitions_root = Path(__file__).parent.parent / "definitions"
        trainer = ChurnModelTrainer(DB_PATH, definitions_root)
        result = trainer.train_baseline(enforce_dq_gate=False)
        assert result.evaluation.auc_roc >= 0.65, (
            f"AUC-ROC {result.evaluation.auc_roc:.3f} < 0.65 threshold"
        )
