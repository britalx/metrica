"""Pydantic models for ETL pipeline run results."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PipelineStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class MetricRunResult(BaseModel):
    metric_id: str
    rows_read: int = 0
    rows_written: int = 0
    duration_seconds: float = 0.0
    status: PipelineStatus = PipelineStatus.SUCCESS
    error: Optional[str] = None
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PipelineRunResult(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    metrics_attempted: int = 0
    metrics_succeeded: int = 0
    metrics_failed: int = 0
    total_rows_written: int = 0
    status: PipelineStatus = PipelineStatus.SUCCESS
    metric_results: list[MetricRunResult] = Field(default_factory=list)
