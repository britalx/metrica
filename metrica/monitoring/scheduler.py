"""DQ scheduling engine — single-shot and daemon modes."""

from __future__ import annotations

import logging
import sys
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import schedule as schedule_lib
import yaml
from pydantic import BaseModel, Field

from metrica.dq.models import Severity
from metrica.monitoring.alerting import write_alert

logger = logging.getLogger("metrica.monitoring.scheduler")


class ScheduleConfig(BaseModel):
    """Parsed dq_schedule.yaml configuration."""

    interval_minutes: int = 60
    cron_expression: str = "0 * * * *"
    run_on_start: bool = True
    db_path: str = "data/metrica_mock.duckdb"
    definitions_root: str = "definitions/"
    alerts_output_dir: str = ".alerts/"
    write_always: bool = False
    write_on_warn: bool = True
    write_on_fail: bool = True
    print_scorecard: bool = True
    run_before_dq: bool = False


class ScheduleRunResult(BaseModel):
    """Result of a single scheduled DQ run."""

    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    metrics_checked: int = 0
    checks_run: int = 0
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    overall_status: Severity = Severity.PASS
    alert_written: bool = False
    error: Optional[str] = None


def load_schedule_config(config_path: Path) -> ScheduleConfig:
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    sched = raw.get("schedule", {})
    db = raw.get("database", {})
    defs = raw.get("definitions", {})
    alerts = raw.get("alerts", {})
    pipeline = raw.get("pipeline", {})

    return ScheduleConfig(
        interval_minutes=sched.get("interval_minutes", 60),
        cron_expression=sched.get("cron_expression", "0 * * * *"),
        run_on_start=sched.get("run_on_start", True),
        db_path=db.get("path", "data/metrica_mock.duckdb"),
        definitions_root=defs.get("root", "definitions/"),
        alerts_output_dir=alerts.get("output_dir", ".alerts/"),
        write_always=alerts.get("write_always", False),
        write_on_warn=alerts.get("write_on_warn", True),
        write_on_fail=alerts.get("write_on_fail", True),
        print_scorecard=alerts.get("print_scorecard", True),
        run_before_dq=pipeline.get("run_before_dq", False),
    )


class DQScheduler:
    """Orchestrates scheduled DQ check runs."""

    def __init__(self, config_path: Path, project_root: Path | None = None):
        self.config = load_schedule_config(config_path)
        self.project_root = project_root or config_path.parent
        self.db_path = self.project_root / self.config.db_path
        self.definitions_root = self.project_root / self.config.definitions_root
        self.alerts_dir = self.project_root / self.config.alerts_output_dir

    def run_once(self, dry_run: bool = False) -> ScheduleRunResult:
        """Execute a single DQ check run, optionally preceded by ETL."""
        # Import here to avoid circular imports
        from scripts.run_dq_checks import print_scorecard, run_dq_checks

        run_id = f"run-{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        result = ScheduleRunResult(run_id=run_id, started_at=started_at)

        try:
            # Optionally run ETL pipeline before DQ checks
            if self.config.run_before_dq and not dry_run:
                self._run_pipeline()

            if dry_run:
                # Load rules to show what would run, but don't execute
                from metrica.registry.loader import DefinitionLoader

                loader = DefinitionLoader(self.definitions_root)
                all_rules = loader.metric_dq_rules()
                result.metrics_checked = len(all_rules)
                result.checks_run = sum(len(r) for r in all_rules.values())
                result.finished_at = datetime.now(UTC)
                result.duration_seconds = (
                    result.finished_at - result.started_at
                ).total_seconds()
                if self.config.print_scorecard:
                    print(f"[DRY RUN] Would check {result.metrics_checked} metrics "
                          f"({result.checks_run} rules). No writes.")
                return result

            # Run actual DQ checks
            dq_results = run_dq_checks(
                db_path=self.db_path, definitions_root=self.definitions_root
            )

            # Compute summary
            result.checks_run = len(dq_results)
            metric_ids = {r["metric_id"] for r in dq_results}
            result.metrics_checked = len(metric_ids)
            result.pass_count = sum(1 for r in dq_results if r["severity"] == "pass")
            result.warn_count = sum(1 for r in dq_results if r["severity"] == "warn")
            result.fail_count = sum(1 for r in dq_results if r["severity"] == "fail")

            if result.fail_count > 0:
                result.overall_status = Severity.FAIL
            elif result.warn_count > 0:
                result.overall_status = Severity.WARN
            else:
                result.overall_status = Severity.PASS

            result.finished_at = datetime.now(UTC)
            result.duration_seconds = (
                result.finished_at - result.started_at
            ).total_seconds()

            # Print scorecard
            if self.config.print_scorecard:
                print_scorecard(dq_results)

            # Write alert if needed
            should_write = (
                self.config.write_always
                or (self.config.write_on_warn and result.overall_status == Severity.WARN)
                or (self.config.write_on_fail and result.overall_status == Severity.FAIL)
            )
            if should_write:
                write_alert(result, dq_results, self.alerts_dir)
                result.alert_written = True

        except Exception:
            result.error = traceback.format_exc()
            result.finished_at = datetime.now(UTC)
            result.duration_seconds = (
                result.finished_at - result.started_at
            ).total_seconds()
            logger.error("DQ run failed: %s", result.error)

            # Write error to log file
            logs_dir = self.project_root / ".logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            with open(logs_dir / "dq_errors.log", "a") as f:
                f.write(f"[{datetime.now(UTC).isoformat()}] {result.error}\n")

        return result

    def _run_pipeline(self):
        """Run ETL pipeline before DQ checks."""
        from metrica.pipeline.runner import PipelineRunner

        logger.info("Running ETL pipeline before DQ checks...")
        runner = PipelineRunner(self.db_path, self.definitions_root)
        pipe_result = runner.run()
        logger.info(
            "Pipeline finished: %d/%d metrics succeeded, %d rows written",
            pipe_result.metrics_succeeded,
            pipe_result.metrics_attempted,
            pipe_result.total_rows_written,
        )

    def run_daemon(self, interval_override: int | None = None):
        """Run DQ checks on a schedule until interrupted."""
        interval = interval_override or self.config.interval_minutes

        print(f"[scheduler] Starting daemon mode — running every {interval}m")
        print(f"[scheduler] DB: {self.db_path}")
        print(f"[scheduler] Press Ctrl+C to stop")

        schedule_lib.every(interval).minutes.do(self.run_once)

        if self.config.run_on_start:
            print("[scheduler] Running initial check...")
            self.run_once()

        try:
            while True:
                schedule_lib.run_pending()
                time.sleep(30)
        except KeyboardInterrupt:
            print("\n[scheduler] Stopped by user")
