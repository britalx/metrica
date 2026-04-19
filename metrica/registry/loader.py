"""YAML loader for metric definitions, CDEs, and source systems."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from metrica.dq.models import DQRule
from metrica.registry.models import CDE, MetricDefinition, SourceSystem


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def load_source(path: Path) -> SourceSystem:
    return SourceSystem(**_load_yaml(path))


def load_cde(path: Path) -> CDE:
    return CDE(**_load_yaml(path))


def load_metric(path: Path) -> MetricDefinition:
    raw = _load_yaml(path)
    # dq_rules are stored alongside but not part of MetricDefinition model
    raw.pop("dq_rules", None)
    return MetricDefinition(**raw)


def load_metric_dq_rules(path: Path) -> list[DQRule]:
    raw = _load_yaml(path)
    metric_id = raw.get("metric_id", "")
    rules = []
    for r in raw.get("dq_rules", []):
        r.setdefault("target_type", "metric")
        r.setdefault("target_id", metric_id)
        r.setdefault("name", r.get("rule_id", ""))
        rules.append(DQRule(**r))
    return rules


def load_all_from_dir(directory: Path, loader) -> list:
    results = []
    if not directory.exists():
        return results
    for p in sorted(directory.glob("*.yaml")):
        results.append(loader(p))
    return results


class DefinitionLoader:
    """Loads all definitions from the definitions/ directory tree."""

    def __init__(self, definitions_root: Path):
        self.root = definitions_root

    def sources(self) -> list[SourceSystem]:
        return load_all_from_dir(self.root / "sources", load_source)

    def cdes(self) -> list[CDE]:
        return load_all_from_dir(self.root / "cdes", load_cde)

    def metrics(self) -> list[MetricDefinition]:
        return load_all_from_dir(self.root / "metrics", load_metric)

    def metric_dq_rules(self) -> dict[str, list[DQRule]]:
        result = {}
        metrics_dir = self.root / "metrics"
        if not metrics_dir.exists():
            return result
        for p in sorted(metrics_dir.glob("*.yaml")):
            rules = load_metric_dq_rules(p)
            if rules:
                result[rules[0].target_id] = rules
        return result
