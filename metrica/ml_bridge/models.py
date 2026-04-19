"""Pydantic models for the ML Feature Bridge."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class FeatureValue(BaseModel):
    metric_id: str
    value: float | int | bool | None = None
    dq_score: float | None = None
    dq_status: str = "unknown"  # "pass" | "warn" | "fail" | "unknown"
    gated_out: bool = False


class FeatureVector(BaseModel):
    customer_id: str
    features: list[FeatureValue]
    metrics_requested: int
    metrics_served: int
    metrics_gated: int
    assembled_at: datetime
    dq_gate_threshold: float


class FeatureRecord(BaseModel):
    """One row in the feature matrix — flat dict of metric_id -> value."""
    customer_id: str
    features: dict[str, float | int | bool | None]
    gated_metrics: list[str] = Field(default_factory=list)


class FeatureMatrix(BaseModel):
    records: list[FeatureRecord]
    total_customers: int
    total_metrics: int
    metrics_served: list[str]
    metrics_gated: list[str]
    gate_threshold: float
    assembled_at: datetime


class GateStatusEntry(BaseModel):
    metric_id: str
    domain: str
    latest_dq_score: float | None = None
    gate_threshold: float
    passes_gate: bool
    blocking_dimension: str | None = None
    last_checked: datetime | None = None


class GateStatusReport(BaseModel):
    entries: list[GateStatusEntry]
    total_metrics: int
    passing: int
    blocked: int
    unknown: int
    gate_threshold: float
    generated_at: datetime
