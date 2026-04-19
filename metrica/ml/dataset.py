"""Dataset preparation for the churn model."""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np

from metrica.ml_bridge import FeatureStore


class ChurnDataset:
    """Builds sklearn-ready arrays from the Metrica Feature Store."""

    def __init__(self, db_path: Path, definitions_root: Path):
        self.db_path = db_path
        self.definitions_root = definitions_root
        self.fs = FeatureStore(db_path, definitions_root)

    def build(
        self,
        exclude_metrics: list[str] | None = None,
        enforce_dq_gate: bool = True,
    ) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
        """Build X, y arrays for model training.

        Returns:
            X: float32 array (n_customers, n_features), NULLs imputed with median
            y: int array (n_customers,) — churn labels
            feature_names: metric_ids corresponding to X columns
            gated_metrics: metric_ids excluded by DQ gate
        """
        exclude = set(exclude_metrics or [])
        exclude.add("churn_label_30d")  # target, not a feature

        # Get the feature matrix (DQ-gated)
        matrix = self.fs.get_feature_matrix(enforce_dq_gate=enforce_dq_gate)
        gated_metrics = list(matrix.metrics_gated)

        # Filter out excluded metrics from served list
        feature_names = [m for m in matrix.metrics_served if m not in exclude]

        # Pull labels directly from DB
        conn = duckdb.connect(str(self.db_path), read_only=True)
        label_rows = conn.execute(
            "SELECT customer_id, churn_label_30d FROM metrics.customer_metrics "
            "ORDER BY customer_id"
        ).fetchall()
        conn.close()

        label_map = {row[0]: row[1] for row in label_rows}

        # Build arrays aligned by customer_id
        n_customers = len(matrix.records)
        n_features = len(feature_names)

        X_raw = np.full((n_customers, n_features), np.nan, dtype=np.float64)
        y = np.zeros(n_customers, dtype=np.int32)

        for i, record in enumerate(matrix.records):
            y[i] = int(label_map.get(record.customer_id, 0))
            for j, fname in enumerate(feature_names):
                val = record.features.get(fname)
                if val is not None:
                    if isinstance(val, bool):
                        X_raw[i, j] = float(val)
                    else:
                        X_raw[i, j] = float(val)

        # Impute NULLs with column median
        null_count = 0
        for j in range(n_features):
            col = X_raw[:, j]
            mask = np.isnan(col)
            n_nulls = int(mask.sum())
            if n_nulls > 0:
                null_count += n_nulls
                valid = col[~mask]
                median_val = float(np.median(valid)) if len(valid) > 0 else 0.0
                col[mask] = median_val

        X = X_raw.astype(np.float32)

        return X, y, feature_names, gated_metrics
