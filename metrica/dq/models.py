"""Pydantic models for the data quality framework."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DQDimension(str, Enum):
    COMPLETENESS = "completeness"
    ACCURACY = "accuracy"
    CONSISTENCY = "consistency"
    TIMELINESS = "timeliness"
    VALIDITY = "validity"


class Severity(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class DQRule(BaseModel):
    """A single data quality rule applied to a metric or CDE."""

    rule_id: str
    name: str
    description: str = ""
    dimension: DQDimension
    target_type: str = Field(description="'metric' or 'cde'")
    target_id: str = Field(description="The metric_id or cde_id being checked")
    check_expression: str = Field(
        description="SQL expression or Python callable reference for the check"
    )
    warn_threshold: float = Field(
        default=0.95, description="Score below this triggers a warning"
    )
    fail_threshold: float = Field(
        default=0.80, description="Score below this triggers a failure"
    )
    enabled: bool = True


class DQScore(BaseModel):
    """Result of a single DQ rule evaluation."""

    rule_id: str
    target_id: str
    dimension: DQDimension
    score: float = Field(ge=0.0, le=1.0)
    severity: Severity
    records_checked: int = 0
    records_failed: int = 0
    details: str = ""
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class DQRunResult(BaseModel):
    """Aggregate result of a DQ run across all rules for a target."""

    run_id: str
    target_id: str
    scores: list[DQScore] = Field(default_factory=list)
    composite_score: float = Field(ge=0.0, le=1.0)
    overall_severity: Severity
    run_started_at: datetime
    run_finished_at: Optional[datetime] = None

    @staticmethod
    def compute_composite(scores: list[DQScore]) -> float:
        if not scores:
            return 0.0
        return sum(s.score for s in scores) / len(scores)

    @staticmethod
    def compute_severity(composite: float, warn: float = 0.95, fail: float = 0.80) -> Severity:
        if composite >= warn:
            return Severity.PASS
        elif composite >= fail:
            return Severity.WARN
        return Severity.FAIL


class DQConfig(BaseModel):
    """Global DQ framework configuration."""

    default_warn_threshold: float = 0.95
    default_fail_threshold: float = 0.80
    ml_gate_threshold: float = 0.90
    alert_channels: list[str] = Field(
        default_factory=lambda: ["log"], description="'log', 'file', 'slack'"
    )
