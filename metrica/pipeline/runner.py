"""ETL pipeline orchestrator — runs transformations for all metrics."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from metrica.pipeline.models import MetricRunResult, PipelineRunResult, PipelineStatus
from metrica.pipeline.transformer import MetricTransformer
from metrica.registry.loader import DefinitionLoader


PIPELINE_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS pipeline;

CREATE TABLE IF NOT EXISTS pipeline.pipeline_runs (
    run_id            VARCHAR PRIMARY KEY,
    started_at        TIMESTAMP NOT NULL,
    finished_at       TIMESTAMP NOT NULL,
    duration_seconds  DOUBLE NOT NULL,
    metrics_attempted INTEGER NOT NULL,
    metrics_succeeded INTEGER NOT NULL,
    metrics_failed    INTEGER NOT NULL,
    total_rows_written INTEGER NOT NULL,
    status            VARCHAR NOT NULL,
    details_json      VARCHAR
);
"""


class PipelineRunner:
    """Orchestrates ETL for all (or selected) metrics."""

    def __init__(self, db_path: Path, definitions_root: Path):
        self.db_path = db_path
        self.definitions_root = definitions_root

    def run(
        self,
        metric_ids: list[str] | None = None,
        dry_run: bool = False,
    ) -> PipelineRunResult:
        started_at = datetime.now(UTC)
        run_id = f"etl-run-{uuid.uuid4().hex[:6]}"

        conn = duckdb.connect(str(self.db_path))
        self._ensure_pipeline_schema(conn)

        loader = DefinitionLoader(self.definitions_root)
        all_metrics = loader.metrics()

        # Filter to requested metrics
        if metric_ids:
            metrics = [m for m in all_metrics if m.metric_id in metric_ids]
        else:
            metrics = all_metrics

        transformer = MetricTransformer(conn)
        metric_results: list[MetricRunResult] = []

        for metric in metrics:
            result = transformer.transform(metric, dry_run=dry_run)
            metric_results.append(result)

        finished_at = datetime.now(UTC)
        duration = (finished_at - started_at).total_seconds()

        succeeded = sum(1 for r in metric_results if r.status == PipelineStatus.SUCCESS)
        failed = sum(1 for r in metric_results if r.status == PipelineStatus.FAILED)
        total_written = sum(r.rows_written for r in metric_results)

        if failed == 0:
            status = PipelineStatus.SUCCESS
        elif succeeded == 0:
            status = PipelineStatus.FAILED
        else:
            status = PipelineStatus.PARTIAL

        pipeline_result = PipelineRunResult(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=round(duration, 3),
            metrics_attempted=len(metrics),
            metrics_succeeded=succeeded,
            metrics_failed=failed,
            total_rows_written=total_written,
            status=status,
            metric_results=metric_results,
        )

        # Persist run summary (skip for dry runs)
        if not dry_run:
            details = json.dumps(
                [r.model_dump(mode="json") for r in metric_results]
            )
            conn.execute(
                "INSERT INTO pipeline.pipeline_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    started_at,
                    finished_at,
                    round(duration, 3),
                    len(metrics),
                    succeeded,
                    failed,
                    total_written,
                    status.value,
                    details,
                ],
            )

        conn.close()
        return pipeline_result

    @staticmethod
    def _ensure_pipeline_schema(conn: duckdb.DuckDBPyConnection):
        conn.execute(PIPELINE_SCHEMA_SQL)
