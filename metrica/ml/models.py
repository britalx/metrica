"""Pydantic models for ML model run results."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FeatureImportance(BaseModel):
    metric_id: str
    coefficient: float
    abs_importance: float
    rank: int


class ModelEvaluation(BaseModel):
    auc_roc: float
    avg_precision: float
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    support_positive: int
    support_negative: int
    threshold_used: float = 0.5


class ModelRunResult(BaseModel):
    run_id: str
    model_type: str
    trained_at: datetime
    training_customers: int
    test_customers: int
    features_used: list[str]
    features_gated: list[str]
    churn_rate_train: float
    churn_rate_test: float
    evaluation: ModelEvaluation
    feature_importances: list[FeatureImportance]
    dq_gate_threshold: float
    notes: str = ""
