"""Tests for the DQ scheduler and alerting system."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

CONFIG_PATH = PROJECT_ROOT / "dq_schedule.yaml"
DB_PATH = PROJECT_ROOT / "data" / "metrica_mock.duckdb"
ALERTS_DIR = PROJECT_ROOT / ".alerts"


@pytest.fixture(scope="module", autouse=True)
def ensure_mock_data():
    """Ensure mock data exists before scheduler tests."""
    if not DB_PATH.exists():
        from generate_mock_data import main as gen_main
        gen_main()


@pytest.fixture
def scheduler():
    from metrica.monitoring.scheduler import DQScheduler
    return DQScheduler(config_path=CONFIG_PATH, project_root=PROJECT_ROOT)


@pytest.fixture
def clean_alerts():
    """Clean .alerts/ before and after test."""
    if ALERTS_DIR.exists():
        shutil.rmtree(ALERTS_DIR)
    yield
    if ALERTS_DIR.exists():
        shutil.rmtree(ALERTS_DIR)


def test_schedule_config_loads():
    """dq_schedule.yaml loads into a valid config object."""
    from metrica.monitoring.scheduler import load_schedule_config
    config = load_schedule_config(CONFIG_PATH)
    assert config.interval_minutes == 60
    assert config.run_on_start is True
    assert config.db_path == "data/metrica_mock.duckdb"
    assert config.definitions_root == "definitions/"
    assert config.write_on_warn is True


def test_run_once_returns_result(scheduler):
    """run_once() returns a ScheduleRunResult with expected fields."""
    result = scheduler.run_once()
    assert result.run_id.startswith("run-")
    assert result.started_at is not None
    assert result.finished_at is not None
    assert result.duration_seconds >= 0
    assert result.metrics_checked == 10
    assert result.checks_run >= 10
    assert result.pass_count + result.warn_count + result.fail_count == result.checks_run
    assert result.error is None


def test_run_once_persists_scores(scheduler):
    """After run_once(), dq.dq_scores has new rows."""
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    before = conn.execute("SELECT COUNT(*) FROM dq.dq_scores").fetchone()[0]
    conn.close()

    scheduler.run_once()

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    after = conn.execute("SELECT COUNT(*) FROM dq.dq_scores").fetchone()[0]
    conn.close()

    assert after > before


def test_alert_written_on_warn(scheduler, clean_alerts):
    """Alert file is written when a WARN is present in results."""
    result = scheduler.run_once()
    # Our mock data has WARNs, so alert should be written
    assert result.overall_status.value == "warn"
    assert result.alert_written is True
    assert ALERTS_DIR.exists()
    alert_files = list(ALERTS_DIR.glob("*_WARN.md"))
    assert len(alert_files) >= 1


def test_alert_file_format(scheduler, clean_alerts):
    """Alert markdown file contains expected sections."""
    scheduler.run_once()
    alert_files = list(ALERTS_DIR.glob("*_WARN.md"))
    assert len(alert_files) >= 1

    content = alert_files[0].read_text()
    assert "# DQ Alert" in content
    assert "**Status**: WARN" in content
    assert "**Run ID**:" in content
    assert "**Duration**:" in content
    assert "**Checks**:" in content
    assert "## Warnings" in content
    assert "## Full Scorecard" in content
    assert "| Metric | Dimension | Score | Status |" in content


def test_latest_updated(scheduler, clean_alerts):
    """latest.md in .alerts/ is updated after each run."""
    scheduler.run_once()
    latest_path = ALERTS_DIR / "latest.md"
    assert latest_path.exists()
    content = latest_path.read_text()
    assert "# DQ Alert" in content


def test_dry_run_does_not_write(scheduler, clean_alerts):
    """--dry-run mode does not write to DB or .alerts/."""
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    before = conn.execute("SELECT COUNT(*) FROM dq.dq_scores").fetchone()[0]
    conn.close()

    result = scheduler.run_once(dry_run=True)

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    after = conn.execute("SELECT COUNT(*) FROM dq.dq_scores").fetchone()[0]
    conn.close()

    assert after == before
    assert result.alert_written is False
    # .alerts/ should not be created
    alert_files = list(ALERTS_DIR.glob("*.md")) if ALERTS_DIR.exists() else []
    assert len(alert_files) == 0
