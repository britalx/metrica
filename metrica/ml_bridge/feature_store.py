"""Feature Store — serves DQ-gated metric features to ML pipelines."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb

from metrica.dq.models import DQConfig
from metrica.ml_bridge.models import (
    FeatureMatrix,
    FeatureRecord,
    FeatureValue,
    FeatureVector,
    GateStatusEntry,
    GateStatusReport,
)
from metrica.registry.loader import DefinitionLoader


class FeatureStore:
    """Serves DQ-gated feature vectors from the metrics layer."""

    def __init__(
        self,
        db_path: Path,
        definitions_root: Path,
        config: DQConfig | None = None,
    ):
        self.db_path = db_path
        self.definitions_root = definitions_root
        self.config = config or DQConfig()
        self._gate_threshold = self.config.ml_gate_threshold
        self._loader = DefinitionLoader(definitions_root)

    # ── DQ Gate inspection ───────────────────────────────────────────

    def _load_latest_dq_scores(self, conn: duckdb.DuckDBPyConnection) -> dict[str, dict]:
        """Return {metric_id: {composite_score, overall_severity, run_started_at, blocking_dimension}}."""
        # Get the latest dq_run per metric (target_id)
        rows = conn.execute("""
            SELECT r.target_id, r.composite_score, r.overall_severity, r.run_started_at
            FROM dq.dq_runs r
            WHERE r.run_started_at = (
                SELECT MAX(r2.run_started_at)
                FROM dq.dq_runs r2
                WHERE r2.target_id = r.target_id
            )
        """).fetchall()

        result = {}
        for target_id, composite, severity, started in rows:
            result[target_id] = {
                "composite_score": composite,
                "overall_severity": severity,
                "run_started_at": started,
            }

        # Find blocking dimension for each metric (lowest-scoring dimension in latest run)
        for target_id, info in result.items():
            dim_rows = conn.execute("""
                SELECT s.dimension, s.score
                FROM dq.dq_scores s
                JOIN dq.dq_runs r ON s.run_id = r.run_id
                WHERE r.target_id = ?
                  AND r.run_started_at = ?
                ORDER BY s.score ASC
                LIMIT 1
            """, [target_id, info["run_started_at"]]).fetchall()
            if dim_rows and dim_rows[0][1] < self._gate_threshold:
                info["blocking_dimension"] = dim_rows[0][0]
            else:
                info["blocking_dimension"] = None

        return result

    def gate_status(self) -> GateStatusReport:
        """Show which metrics pass/fail the DQ gate and why."""
        conn = duckdb.connect(str(self.db_path), read_only=True)
        metrics = self._loader.metrics()
        active_metrics = [m for m in metrics if m.status == "active"]
        dq_scores = self._load_latest_dq_scores(conn)
        conn.close()

        entries = []
        passing = blocked = unknown = 0

        for m in active_metrics:
            dq_info = dq_scores.get(m.metric_id)
            if dq_info is None:
                entries.append(GateStatusEntry(
                    metric_id=m.metric_id,
                    domain=m.domain.value,
                    latest_dq_score=None,
                    gate_threshold=self._gate_threshold,
                    passes_gate=True,  # unknown = allowed by default
                    blocking_dimension=None,
                    last_checked=None,
                ))
                unknown += 1
            elif dq_info["composite_score"] >= self._gate_threshold:
                entries.append(GateStatusEntry(
                    metric_id=m.metric_id,
                    domain=m.domain.value,
                    latest_dq_score=dq_info["composite_score"],
                    gate_threshold=self._gate_threshold,
                    passes_gate=True,
                    blocking_dimension=None,
                    last_checked=dq_info["run_started_at"],
                ))
                passing += 1
            else:
                entries.append(GateStatusEntry(
                    metric_id=m.metric_id,
                    domain=m.domain.value,
                    latest_dq_score=dq_info["composite_score"],
                    gate_threshold=self._gate_threshold,
                    passes_gate=False,
                    blocking_dimension=dq_info["blocking_dimension"],
                    last_checked=dq_info["run_started_at"],
                ))
                blocked += 1

        return GateStatusReport(
            entries=entries,
            total_metrics=len(active_metrics),
            passing=passing,
            blocked=blocked,
            unknown=unknown,
            gate_threshold=self._gate_threshold,
            generated_at=datetime.now(UTC),
        )

    def passed_metrics(self) -> list[str]:
        """metric_ids that currently pass the DQ gate."""
        report = self.gate_status()
        return [e.metric_id for e in report.entries if e.passes_gate]

    def blocked_metrics(self) -> list[str]:
        """metric_ids currently blocked by the DQ gate."""
        report = self.gate_status()
        return [e.metric_id for e in report.entries if not e.passes_gate]

    # ── Feature retrieval ────────────────────────────────────────────

    def _resolve_metrics(self, metric_ids: list[str] | None) -> list[str]:
        """Resolve metric_ids to list of active metric IDs."""
        all_metrics = self._loader.metrics()
        active = [m.metric_id for m in all_metrics if m.status == "active"]
        if metric_ids:
            return [mid for mid in metric_ids if mid in active]
        return active

    def _get_dq_status(self, dq_scores: dict, metric_id: str) -> tuple[float | None, str]:
        """Return (score, status_str) for a metric."""
        info = dq_scores.get(metric_id)
        if info is None:
            return None, "unknown"
        return info["composite_score"], info["overall_severity"]

    def get_features(
        self,
        customer_id: str,
        metric_ids: list[str] | None = None,
        enforce_dq_gate: bool = True,
    ) -> FeatureVector:
        """Return feature values for one customer, with DQ gate applied."""
        conn = duckdb.connect(str(self.db_path), read_only=True)
        resolved = self._resolve_metrics(metric_ids)
        dq_scores = self._load_latest_dq_scores(conn)

        # Get customer row from metrics.customer_metrics
        cols = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='metrics' AND table_name='customer_metrics'"
        ).fetchall()
        available_cols = {r[0] for r in cols}

        # Fetch the customer's data
        row_data = {}
        select_cols = [mid for mid in resolved if mid in available_cols]
        if select_cols:
            col_list = ", ".join(select_cols)
            result = conn.execute(
                f"SELECT {col_list} FROM metrics.customer_metrics WHERE customer_id = ?",
                [customer_id],
            ).fetchone()
            if result:
                row_data = dict(zip(select_cols, result))

        conn.close()

        features = []
        gated_count = 0
        for mid in resolved:
            score, status = self._get_dq_status(dq_scores, mid)
            gated = enforce_dq_gate and score is not None and score < self._gate_threshold

            if gated:
                gated_count += 1
                features.append(FeatureValue(
                    metric_id=mid,
                    value=None,
                    dq_score=score,
                    dq_status=status,
                    gated_out=True,
                ))
            else:
                features.append(FeatureValue(
                    metric_id=mid,
                    value=row_data.get(mid),
                    dq_score=score,
                    dq_status=status,
                    gated_out=False,
                ))

        return FeatureVector(
            customer_id=customer_id,
            features=features,
            metrics_requested=len(resolved),
            metrics_served=len(resolved) - gated_count,
            metrics_gated=gated_count,
            assembled_at=datetime.now(UTC),
            dq_gate_threshold=self._gate_threshold,
        )

    def get_feature_matrix(
        self,
        customer_ids: list[str] | None = None,
        metric_ids: list[str] | None = None,
        enforce_dq_gate: bool = True,
        format: Literal["dict", "records"] = "records",
    ) -> FeatureMatrix:
        """Return feature matrix for multiple customers."""
        conn = duckdb.connect(str(self.db_path), read_only=True)
        resolved = self._resolve_metrics(metric_ids)
        dq_scores = self._load_latest_dq_scores(conn)

        # Determine which metrics pass the gate
        served = []
        gated = []
        for mid in resolved:
            score, _ = self._get_dq_status(dq_scores, mid)
            if enforce_dq_gate and score is not None and score < self._gate_threshold:
                gated.append(mid)
            else:
                served.append(mid)

        # Query available columns
        cols = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='metrics' AND table_name='customer_metrics'"
        ).fetchall()
        available_cols = {r[0] for r in cols}
        query_cols = [mid for mid in served if mid in available_cols]

        # Build query
        if customer_ids:
            placeholders = ", ".join("?" for _ in customer_ids)
            where_clause = f"WHERE customer_id IN ({placeholders})"
            params = customer_ids
        else:
            where_clause = ""
            params = []

        if query_cols:
            col_list = "customer_id, " + ", ".join(query_cols)
        else:
            col_list = "customer_id"

        rows = conn.execute(
            f"SELECT {col_list} FROM metrics.customer_metrics {where_clause}",
            params,
        ).fetchall()
        conn.close()

        # Build records
        records = []
        for row in rows:
            cust_id = row[0]
            feature_dict = {}
            for i, col in enumerate(query_cols):
                feature_dict[col] = row[i + 1]
            records.append(FeatureRecord(
                customer_id=cust_id,
                features=feature_dict,
                gated_metrics=gated,
            ))

        return FeatureMatrix(
            records=records,
            total_customers=len(records),
            total_metrics=len(resolved),
            metrics_served=served,
            metrics_gated=gated,
            gate_threshold=self._gate_threshold,
            assembled_at=datetime.now(UTC),
        )
