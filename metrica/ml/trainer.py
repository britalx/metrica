"""Churn model trainer with evaluation and persistence."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from metrica.ml.dataset import ChurnDataset
from metrica.ml.models import FeatureImportance, ModelEvaluation, ModelRunResult


class ChurnModelTrainer:
    """Trains and evaluates a baseline logistic regression churn model."""

    def __init__(
        self,
        db_path: Path,
        definitions_root: Path,
        random_state: int = 42,
    ):
        self.db_path = db_path
        self.definitions_root = definitions_root
        self.random_state = random_state
        self._dataset = ChurnDataset(db_path, definitions_root)

    def train_baseline(
        self,
        test_size: float = 0.2,
        enforce_dq_gate: bool = True,
        max_iter: int = 1000,
    ) -> ModelRunResult:
        """Full training pipeline: build data, split, scale, train, evaluate, persist."""
        X, y, feature_names, gated_metrics = self._dataset.build(
            enforce_dq_gate=enforce_dq_gate,
        )

        # Train/test split (stratified)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=test_size,
            stratify=y,
            random_state=self.random_state,
        )

        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # Train logistic regression
        model = LogisticRegression(
            max_iter=max_iter,
            random_state=self.random_state,
            class_weight="balanced",
        )
        model.fit(X_train_scaled, y_train)

        # Predict
        y_pred = model.predict(X_test_scaled)
        y_prob = model.predict_proba(X_test_scaled)[:, 1]

        # Evaluation metrics
        tn, fp, fn, tp = confusion_matrix(y_test, y_pred).ravel()

        evaluation = ModelEvaluation(
            auc_roc=float(roc_auc_score(y_test, y_prob)),
            avg_precision=float(average_precision_score(y_test, y_prob)),
            accuracy=float(accuracy_score(y_test, y_pred)),
            precision=float(precision_score(y_test, y_pred, zero_division=0)),
            recall=float(recall_score(y_test, y_pred, zero_division=0)),
            f1_score=float(f1_score(y_test, y_pred, zero_division=0)),
            true_positives=int(tp),
            true_negatives=int(tn),
            false_positives=int(fp),
            false_negatives=int(fn),
            support_positive=int(tp + fn),
            support_negative=int(tn + fp),
        )

        # Feature importances from coefficients
        coefficients = model.coef_[0]
        abs_importance = np.abs(coefficients)
        ranked_indices = np.argsort(-abs_importance)

        importances = []
        for rank, idx in enumerate(ranked_indices, start=1):
            importances.append(FeatureImportance(
                metric_id=feature_names[idx],
                coefficient=float(coefficients[idx]),
                abs_importance=float(abs_importance[idx]),
                rank=rank,
            ))

        run_id = f"model-run-{uuid.uuid4().hex[:6]}"
        result = ModelRunResult(
            run_id=run_id,
            model_type="logistic_regression",
            trained_at=datetime.now(UTC),
            training_customers=len(y_train),
            test_customers=len(y_test),
            features_used=feature_names,
            features_gated=gated_metrics,
            churn_rate_train=float(y_train.mean()),
            churn_rate_test=float(y_test.mean()),
            evaluation=evaluation,
            feature_importances=importances,
            dq_gate_threshold=self._dataset.fs._gate_threshold,
        )

        # Persist to DB
        conn = duckdb.connect(str(self.db_path))
        self._ensure_ml_schema(conn)
        self._persist_result(result, conn)
        conn.close()

        return result

    def _ensure_ml_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("CREATE SCHEMA IF NOT EXISTS ml")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ml.model_runs (
                run_id              VARCHAR PRIMARY KEY,
                model_type          VARCHAR NOT NULL,
                trained_at          TIMESTAMP NOT NULL,
                training_customers  INTEGER NOT NULL,
                test_customers      INTEGER NOT NULL,
                features_used_json  VARCHAR NOT NULL,
                features_gated_json VARCHAR NOT NULL,
                churn_rate_train    DOUBLE NOT NULL,
                churn_rate_test     DOUBLE NOT NULL,
                auc_roc             DOUBLE NOT NULL,
                avg_precision       DOUBLE NOT NULL,
                accuracy            DOUBLE NOT NULL,
                precision_score     DOUBLE NOT NULL,
                recall_score        DOUBLE NOT NULL,
                f1_score            DOUBLE NOT NULL,
                dq_gate_threshold   DOUBLE NOT NULL,
                evaluation_json     VARCHAR NOT NULL,
                importances_json    VARCHAR NOT NULL,
                notes               VARCHAR DEFAULT ''
            )
        """)

    def _persist_result(self, result: ModelRunResult, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute(
            """INSERT INTO ml.model_runs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            [
                result.run_id,
                result.model_type,
                result.trained_at,
                result.training_customers,
                result.test_customers,
                json.dumps(result.features_used),
                json.dumps(result.features_gated),
                result.churn_rate_train,
                result.churn_rate_test,
                result.evaluation.auc_roc,
                result.evaluation.avg_precision,
                result.evaluation.accuracy,
                result.evaluation.precision,
                result.evaluation.recall,
                result.evaluation.f1_score,
                result.dq_gate_threshold,
                result.evaluation.model_dump_json(),
                json.dumps([fi.model_dump() for fi in result.feature_importances]),
                result.notes,
            ],
        )
