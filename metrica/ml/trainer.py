"""Churn model trainer with evaluation and persistence."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
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
from metrica.ml.models import (
    DisagreementRecord,
    FeatureImportance,
    ModelEvaluation,
    ModelRunResult,
    MultiModelResult,
)


class ChurnModelTrainer:
    """Trains and evaluates churn models with multi-model and champion/challenger support."""

    # Default model configurations
    DEFAULT_MODELS = {
        "logistic_regression": lambda rs: LogisticRegression(
            max_iter=1000, random_state=rs, class_weight="balanced",
        ),
        "random_forest": lambda rs: RandomForestClassifier(
            n_estimators=100, random_state=rs, class_weight="balanced",
        ),
        "gradient_boosting": lambda rs: GradientBoostingClassifier(
            n_estimators=100, random_state=rs,
        ),
    }

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

    def train_multi(
        self,
        test_size: float = 0.2,
        enforce_dq_gate: bool = True,
        model_types: list[str] | None = None,
        disagreement_threshold: float = 0.3,
    ) -> MultiModelResult:
        """Train multiple models independently on the same split, with disagreement tracking.

        Args:
            test_size: Fraction of data for test set.
            enforce_dq_gate: Whether to apply DQ gating.
            model_types: List of model type keys (defaults to all DEFAULT_MODELS).
            disagreement_threshold: Probability divergence threshold for flagging.

        Returns:
            MultiModelResult with per-model results and disagreement records.
        """
        if model_types is None:
            model_types = list(self.DEFAULT_MODELS.keys())

        X, y, feature_names, gated_metrics = self._dataset.build(
            enforce_dq_gate=enforce_dq_gate,
        )

        # Shared train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=test_size,
            stratify=y,
            random_state=self.random_state,
        )

        # Shared scaler
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        run_group_id = f"group-{uuid.uuid4().hex[:6]}"
        model_results: list[ModelRunResult] = []
        all_probs: dict[str, np.ndarray] = {}

        conn = duckdb.connect(str(self.db_path))
        self._ensure_ml_schema(conn)

        for model_type in model_types:
            if model_type not in self.DEFAULT_MODELS:
                raise ValueError(f"Unknown model type: {model_type}")

            model = self.DEFAULT_MODELS[model_type](self.random_state)
            model.fit(X_train_scaled, y_train)

            y_pred = model.predict(X_test_scaled)
            y_prob = model.predict_proba(X_test_scaled)[:, 1]
            all_probs[model_type] = y_prob

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

            importances = self._extract_importances(model, model_type, feature_names)

            run_id = f"model-run-{uuid.uuid4().hex[:6]}"
            result = ModelRunResult(
                run_id=run_id,
                model_type=model_type,
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
                run_group_id=run_group_id,
            )

            self._persist_result(result, conn)
            model_results.append(result)

        # Disagreement tracking
        disagreements = self._compute_disagreements(
            X_test, y_test, all_probs, disagreement_threshold, self._dataset,
        )

        # Persist disagreements
        self._ensure_disagreement_table(conn)
        for d in disagreements:
            conn.execute(
                "INSERT INTO ml.model_disagreements VALUES (?, ?, ?, ?, ?)",
                [run_group_id, d.customer_id, json.dumps(d.predictions),
                 d.max_divergence, d.flagged],
            )

        conn.close()

        flagged_count = sum(1 for d in disagreements if d.flagged)
        return MultiModelResult(
            run_group_id=run_group_id,
            model_results=model_results,
            disagreements=disagreements,
            disagreement_threshold=disagreement_threshold,
            flagged_count=flagged_count,
            total_customers=len(y_test),
        )

    def promote_champion(self, run_id: str) -> None:
        """Promote a model run to champion status, demoting any current champion."""
        conn = duckdb.connect(str(self.db_path))
        self._ensure_ml_schema(conn)
        conn.execute("UPDATE ml.model_runs SET is_champion = FALSE WHERE is_champion = TRUE")
        conn.execute("UPDATE ml.model_runs SET is_champion = TRUE WHERE run_id = ?", [run_id])
        conn.close()

    def get_champion(self) -> str | None:
        """Return the run_id of the current champion model, or None."""
        conn = duckdb.connect(str(self.db_path), read_only=True)
        try:
            row = conn.execute(
                "SELECT run_id FROM ml.model_runs WHERE is_champion = TRUE LIMIT 1"
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    @staticmethod
    def _extract_importances(
        model: object, model_type: str, feature_names: list[str],
    ) -> list[FeatureImportance]:
        """Extract feature importances from a fitted model."""
        if model_type == "logistic_regression":
            raw = model.coef_[0]
        elif hasattr(model, "feature_importances_"):
            raw = model.feature_importances_
        else:
            raw = np.zeros(len(feature_names))

        abs_imp = np.abs(raw)
        ranked_indices = np.argsort(-abs_imp)

        importances = []
        for rank, idx in enumerate(ranked_indices, start=1):
            importances.append(FeatureImportance(
                metric_id=feature_names[idx],
                coefficient=float(raw[idx]),
                abs_importance=float(abs_imp[idx]),
                rank=rank,
            ))
        return importances

    @staticmethod
    def _compute_disagreements(
        X_test: np.ndarray,
        y_test: np.ndarray,
        all_probs: dict[str, np.ndarray],
        threshold: float,
        dataset: ChurnDataset,
    ) -> list[DisagreementRecord]:
        """Compute per-customer disagreement records across models."""
        n_test = X_test.shape[0]
        records = []

        for i in range(n_test):
            preds = {mt: float(probs[i]) for mt, probs in all_probs.items()}
            prob_values = list(preds.values())
            max_div = max(prob_values) - min(prob_values)
            flagged = max_div > threshold
            cid = f"test-customer-{i}"
            records.append(DisagreementRecord(
                customer_id=cid,
                predictions=preds,
                max_divergence=round(max_div, 4),
                flagged=flagged,
            ))
        return records

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
                notes               VARCHAR DEFAULT '',
                run_group_id        VARCHAR,
                is_champion         BOOLEAN DEFAULT FALSE
            )
        """)

    def _ensure_disagreement_table(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ml.model_disagreements (
                run_group_id    VARCHAR NOT NULL,
                customer_id     VARCHAR NOT NULL,
                predictions_json VARCHAR NOT NULL,
                max_divergence  DOUBLE NOT NULL,
                flagged         BOOLEAN NOT NULL
            )
        """)

    def _persist_result(self, result: ModelRunResult, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute(
            """INSERT INTO ml.model_runs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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
                result.run_group_id,
                result.is_champion,
            ],
        )
