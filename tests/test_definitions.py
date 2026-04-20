"""Tests for definition loading and model validation."""

from pathlib import Path

from metrica.registry.loader import DefinitionLoader
from metrica.registry.models import Domain, RefreshCadence


DEFINITIONS_ROOT = Path(__file__).parent.parent / "definitions"


def test_load_sources():
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    sources = loader.sources()
    assert len(sources) == 6
    ids = {s.source_id for s in sources}
    assert ids == {"crm", "billing", "contact_center", "cdr", "network", "app_events"}


def test_load_cdes():
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    cdes = loader.cdes()
    assert len(cdes) >= 3
    for cde in cdes:
        assert cde.cde_id
        assert cde.source_system


def test_load_metrics():
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    metrics = loader.metrics()
    assert len(metrics) == 52

    by_id = {m.metric_id: m for m in metrics}

    tenure = by_id["tenure_months"]
    assert tenure.domain == Domain.CONTRACT
    assert tenure.refresh_cadence == RefreshCadence.DAILY
    assert tenure.unit == "months"
    assert "crm.activation_date" in tenure.lineage.upstream_cdes

    charges = by_id["monthly_charges"]
    assert charges.domain == Domain.BILLING
    assert charges.unit == "USD"

    calls = by_id["support_calls_30d"]
    assert calls.domain == Domain.SERVICE
    assert len(calls.lineage.upstream_cdes) == 2


def test_load_dq_rules():
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    rules = loader.metric_dq_rules()
    assert "tenure_months" in rules
    assert "monthly_charges" in rules
    assert "support_calls_30d" in rules
    # Each metric should have multiple DQ rules
    for metric_id, metric_rules in rules.items():
        assert len(metric_rules) >= 2
        for rule in metric_rules:
            assert rule.rule_id
            assert rule.dimension
            assert rule.target_type == "metric"
            assert rule.target_id == metric_id


def test_all_metrics_have_required_fields():
    """Every metric YAML has the required fields and at least 2 DQ rules."""
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    metrics = loader.metrics()
    rules = loader.metric_dq_rules()
    assert len(metrics) >= 40, f"Expected >=40 metrics, got {len(metrics)}"

    for m in metrics:
        assert m.metric_id, "metric_id is required"
        assert m.name, "name is required"
        assert m.domain, "domain is required"
        assert m.data_type, "data_type is required"
        assert m.status in ("active", "draft", "deprecated"), f"Bad status: {m.status}"

    # Every metric has at least 2 DQ rules
    for metric_id, metric_rules in rules.items():
        assert len(metric_rules) >= 2, f"{metric_id} has < 2 DQ rules"
