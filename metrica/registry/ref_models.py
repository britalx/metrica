"""Pydantic models for reference data: systems, code sets, crosswalks, and hierarchies."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# --- Enums ---


class SystemClassification(str, Enum):
    DATA_WAREHOUSE = "data_warehouse"
    DATA_PRODUCT = "data_product"


class LifecycleStatus(str, Enum):
    DEV = "dev"
    PROD = "prod"
    DECOMMISSIONED = "decommissioned"


class MappingType(str, Enum):
    ONE_TO_ONE = "one-to-one"
    MANY_TO_ONE = "many-to-one"
    ONE_TO_MANY = "one-to-many"


# --- Base ---


class BiTemporalMixin(BaseModel):
    """Business-effective date range (system dates are managed by the pipeline)."""

    biz_effective_from: date
    biz_effective_to: date

    @model_validator(mode="after")
    def _check_date_order(self) -> "BiTemporalMixin":
        if self.biz_effective_from > self.biz_effective_to:
            raise ValueError(
                f"biz_effective_from ({self.biz_effective_from}) must be <= "
                f"biz_effective_to ({self.biz_effective_to})"
            )
        return self


# --- System ---


class SystemDefinition(BiTemporalMixin):
    """A source or target system in the data landscape."""

    system_code: str = Field(description="Unique system identifier (PK)")
    name: str
    description: str = ""
    business_domain: str = Field(description="e.g. customer_management, revenue")
    classification: SystemClassification
    lifecycle_status: LifecycleStatus


# --- Code Set ---


class CodeValue(BiTemporalMixin):
    """A single code value within a code set."""

    code: str
    label: str = ""
    description: str = ""


class CodeSetDefinition(BiTemporalMixin):
    """A container of related code values belonging to one system."""

    system_code: str = Field(description="FK to SystemDefinition.system_code")
    codeset_code: str = Field(description="Unique within system")
    name: str
    description: str = ""
    owner_domain: str = ""
    values: list[CodeValue] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_no_overlapping_codes(self) -> "CodeSetDefinition":
        """Ensure no two values with the same code have overlapping business dates."""
        by_code: dict[str, list[CodeValue]] = {}
        for v in self.values:
            by_code.setdefault(v.code, []).append(v)
        for code, entries in by_code.items():
            sorted_entries = sorted(entries, key=lambda e: e.biz_effective_from)
            for i in range(len(sorted_entries) - 1):
                if sorted_entries[i].biz_effective_to >= sorted_entries[i + 1].biz_effective_from:
                    raise ValueError(
                        f"Overlapping business dates for code '{code}' in codeset "
                        f"'{self.codeset_code}'"
                    )
        return self


# --- Crosswalk ---


class OneToOneMapping(BiTemporalMixin):
    """A single one-to-one mapping between source and target codes."""

    source_code: str
    target_code: str


class ManyToOneMapping(BiTemporalMixin):
    """Multiple source codes mapping to a single target code."""

    source_codes: list[str] = Field(min_length=1)
    target_code: str


class RoutingRule(BaseModel):
    """A conditional routing rule for one-to-many mappings."""

    when: Optional[str] = None
    target_code: Optional[str] = None
    default: Optional[str] = None

    @model_validator(mode="after")
    def _check_condition_or_default(self) -> "RoutingRule":
        has_when = self.when is not None
        has_default = self.default is not None
        has_target = self.target_code is not None
        if has_when and has_default:
            raise ValueError("A routing rule cannot have both 'when' and 'default'")
        if has_when and not has_target:
            raise ValueError("A conditional routing rule must have 'target_code'")
        if has_default and has_target:
            raise ValueError("A default rule uses 'default' as the target, not 'target_code'")
        if not has_when and not has_default:
            raise ValueError("Each routing rule must have either 'when' or 'default'")
        return self

    @property
    def resolved_target(self) -> str:
        """Return the effective target code regardless of rule type."""
        return self.target_code if self.target_code is not None else self.default  # type: ignore[return-value]


class OneToManyMapping(BiTemporalMixin):
    """A single source code mapping to multiple targets via routing rules."""

    source_code: str
    routing_rules: list[RoutingRule] = Field(min_length=1)


class CrosswalkDefinition(BiTemporalMixin):
    """A container of code mappings between a source and target system."""

    source_system: str = Field(description="FK to SystemDefinition.system_code")
    target_system: str = Field(description="FK to SystemDefinition.system_code")
    crosswalk_code: str = Field(description="Unique within source+target pair")
    name: str
    description: str = ""
    mapping_type: MappingType
    mappings: list[OneToOneMapping | ManyToOneMapping | OneToManyMapping] = Field(
        min_length=1
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_mappings(cls, data: dict) -> dict:  # type: ignore[override]
        """Parse mappings according to the declared mapping_type."""
        if not isinstance(data, dict):
            return data
        mt = data.get("mapping_type", "")
        raw = data.get("mappings", [])
        parsed = []
        for m in raw:
            if mt == "one-to-one":
                parsed.append(OneToOneMapping(**m))
            elif mt == "many-to-one":
                parsed.append(ManyToOneMapping(**m))
            elif mt == "one-to-many":
                parsed.append(OneToManyMapping(**m))
            else:
                parsed.append(m)
        data["mappings"] = parsed
        return data


# --- Hierarchy ---


class HierarchyNode(BiTemporalMixin):
    """A single node in a hierarchy tree."""

    node_code: str
    level: str
    parent_code: Optional[str] = None
    label: str = ""


class HierarchyDefinition(BiTemporalMixin):
    """A container for a hierarchical tree structure."""

    system_code: str = Field(description="FK to SystemDefinition.system_code")
    hierarchy_code: str = Field(description="Unique within system")
    name: str
    description: str = ""
    levels: list[str] = Field(min_length=1, description="Ordered root → leaf")
    nodes: list[HierarchyNode] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_valid_levels(self) -> "HierarchyDefinition":
        """Ensure every node's level is in the declared levels list."""
        valid = set(self.levels)
        for node in self.nodes:
            if node.level not in valid:
                raise ValueError(
                    f"Node '{node.node_code}' has level '{node.level}' which is not "
                    f"in declared levels {self.levels}"
                )
        return self

    @model_validator(mode="after")
    def _check_no_overlapping_nodes(self) -> "HierarchyDefinition":
        """Ensure no two records for the same node_code have overlapping business dates."""
        by_node: dict[str, list[HierarchyNode]] = {}
        for n in self.nodes:
            by_node.setdefault(n.node_code, []).append(n)
        for node_code, entries in by_node.items():
            sorted_entries = sorted(entries, key=lambda e: e.biz_effective_from)
            for i in range(len(sorted_entries) - 1):
                if sorted_entries[i].biz_effective_to >= sorted_entries[i + 1].biz_effective_from:
                    raise ValueError(
                        f"Overlapping business dates for node '{node_code}' in "
                        f"hierarchy '{self.hierarchy_code}'"
                    )
        return self
