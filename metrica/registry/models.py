"""Pydantic models for the metric registry: metrics, CDEs, sources, and lineage."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RefreshCadence(str, Enum):
    REAL_TIME = "real_time"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Domain(str, Enum):
    USAGE = "usage_behavior"
    BILLING = "billing_financial"
    CONTRACT = "contract_account"
    SERVICE = "customer_service"
    NETWORK = "network_quality"
    ENGAGEMENT = "behavioral_engagement"
    DERIVED = "derived_engineered"


class Sensitivity(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class DataType(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    DATE = "date"
    TIMESTAMP = "timestamp"
    BOOLEAN = "boolean"


class SourceSystem(BaseModel):
    """A data source system feeding metrics."""

    source_id: str = Field(description="Unique identifier, e.g. 'crm', 'billing', 'cdr'")
    name: str
    description: str = ""
    system_type: str = Field(description="e.g. 'database', 'api', 'file', 'stream'")
    connection_hint: str = Field(
        default="", description="How to connect — table name, endpoint, file path"
    )


class CDE(BaseModel):
    """Critical Data Element — an atomic data field that metrics depend on."""

    cde_id: str = Field(description="Unique identifier, e.g. 'crm.activation_date'")
    name: str
    description: str = ""
    source_system: str = Field(description="References a SourceSystem.source_id")
    source_field: str = Field(description="Column/field name in the source system")
    data_type: DataType
    business_owner: str = ""
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    update_frequency: RefreshCadence = RefreshCadence.DAILY
    nullable: bool = False


class SourceMapping(BaseModel):
    """How a metric is derived from source data."""

    source_system: str = Field(description="References a SourceSystem.source_id")
    source_table: str = ""
    source_fields: list[str] = Field(default_factory=list)
    transformation: str = Field(
        default="", description="SQL expression or description of the transformation logic"
    )
    target_table: str = ""
    target_column: str = ""


class Lineage(BaseModel):
    """Upstream dependencies and downstream consumers."""

    upstream_metrics: list[str] = Field(
        default_factory=list, description="Metric IDs this metric depends on"
    )
    upstream_cdes: list[str] = Field(
        default_factory=list, description="CDE IDs this metric depends on"
    )
    downstream_consumers: list[str] = Field(
        default_factory=list,
        description="Dashboards, reports, ML features that consume this metric",
    )


class MetricDefinition(BaseModel):
    """Canonical metric definition — the core unit of Metrica's registry."""

    metric_id: str = Field(description="Unique identifier, e.g. 'tenure_months'")
    name: str = Field(description="Human-readable business name")
    description: str = ""
    domain: Domain
    owner: str = Field(default="", description="Team or person responsible")
    refresh_cadence: RefreshCadence = RefreshCadence.DAILY
    data_type: DataType = DataType.FLOAT
    unit: str = Field(default="", description="e.g. 'months', 'USD', 'count'")
    source_mappings: list[SourceMapping] = Field(default_factory=list)
    lineage: Lineage = Field(default_factory=Lineage)
    tags: list[str] = Field(default_factory=list)
    version: int = 1
    created_date: Optional[date] = None
    last_modified: Optional[date] = None
    status: str = Field(default="active", description="active, deprecated, draft")
