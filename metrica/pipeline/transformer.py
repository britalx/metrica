"""Per-metric SQL transformer — executes source-to-target transformations."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

import duckdb

from metrica.pipeline.models import MetricRunResult, PipelineStatus
from metrica.registry.models import MetricDefinition


class MetricTransformer:
    """Executes the source-to-target SQL for a single metric."""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self.conn = conn

    def transform(
        self, metric: MetricDefinition, dry_run: bool = False
    ) -> MetricRunResult:
        started = time.monotonic()
        try:
            sql = self._build_select_sql(metric)

            if dry_run:
                # Execute the SELECT to count rows but don't write
                rows = self.conn.execute(sql).fetchall()
                duration = time.monotonic() - started
                return MetricRunResult(
                    metric_id=metric.metric_id,
                    rows_read=len(rows),
                    rows_written=0,
                    duration_seconds=round(duration, 3),
                    status=PipelineStatus.SUCCESS,
                )

            # Build and execute upsert
            target_col = metric.metric_id
            upsert_sql = f"""
                INSERT INTO metrics.customer_metrics (customer_id, {target_col}, last_updated)
                SELECT customer_id, {target_col}, CURRENT_TIMESTAMP FROM ({sql})
                ON CONFLICT (customer_id) DO UPDATE SET
                    {target_col} = excluded.{target_col},
                    last_updated = excluded.last_updated
            """

            # Count rows from the SELECT first
            count_row = self.conn.execute(f"SELECT COUNT(*) FROM ({sql})").fetchone()
            rows_read = count_row[0] if count_row else 0

            self.conn.execute(upsert_sql)

            # Count affected rows (rows that now have a non-null value for this metric)
            rows_written = rows_read

            duration = time.monotonic() - started
            return MetricRunResult(
                metric_id=metric.metric_id,
                rows_read=rows_read,
                rows_written=rows_written,
                duration_seconds=round(duration, 3),
                status=PipelineStatus.SUCCESS,
            )

        except Exception as e:
            duration = time.monotonic() - started
            return MetricRunResult(
                metric_id=metric.metric_id,
                duration_seconds=round(duration, 3),
                status=PipelineStatus.FAILED,
                error=str(e),
            )

    def _build_select_sql(self, metric: MetricDefinition) -> str:
        """Build executable SELECT SQL from metric definition."""
        if not metric.source_mappings:
            raise ValueError(f"No source_mappings for metric {metric.metric_id}")

        mapping = metric.source_mappings[0]
        transformation = mapping.transformation.strip()
        source_table = mapping.source_table
        target_col = metric.metric_id

        # If transformation is a full SELECT, qualify table names with raw. schema
        if re.match(r"(?i)^\s*SELECT\b", transformation):
            sql = self._qualify_table_refs(transformation, source_table)
        else:
            # Expression-only: wrap in a SELECT from the qualified source table
            sql = (
                f"SELECT customer_id, "
                f"CAST(({transformation}) AS {self._duckdb_type(metric.data_type.value)}) "
                f"AS {target_col} "
                f"FROM raw.{source_table}"
            )

        # Ensure the metric column is aliased correctly
        return sql

    def _qualify_table_refs(self, sql: str, source_table: str) -> str:
        """Prefix unqualified table references with raw. schema."""
        # Replace unqualified references to the source table with raw.source_table
        # Handles: FROM source_table, JOIN source_table, FROM source_table alias
        pattern = rf"\b{re.escape(source_table)}\b"
        # Only replace if not already qualified with a schema prefix
        result = re.sub(
            rf"(?<!\.)(?<!\w){re.escape(source_table)}\b",
            f"raw.{source_table}",
            sql,
        )
        return result

    @staticmethod
    def _duckdb_type(data_type: str) -> str:
        return {
            "integer": "INTEGER",
            "float": "DOUBLE",
            "string": "VARCHAR",
            "date": "DATE",
            "timestamp": "TIMESTAMP",
            "boolean": "BOOLEAN",
        }.get(data_type, "VARCHAR")
