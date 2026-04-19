# Metrica

**Metric management system and semantic layer for telecom.**

Metrica governs the full lifecycle of business metrics — from raw source data to curated, quality-assured, monitored metrics ready for analytics and machine learning.

## Why Metrica?

Before any ML model can trust its features, the underlying metrics need to be **governed, tracked, and quality-assured end-to-end**. Metrica provides:

- **Canonical metric registry** — every metric has a unique ID, owner, domain, lineage, and versioned definition
- **Critical Data Elements (CDEs)** — atomic data fields with source provenance and sensitivity classification
- **5-dimension DQ framework** — completeness, accuracy, consistency, timeliness, validity — scored 0.0–1.0 per metric per run
- **ML feature bridge** — metrics serve as the authoritative source for ML features with DQ gates

## Project Structure

```
metrica/
├── definitions/              # YAML-based metric/CDE/source definitions
│   ├── metrics/              # One YAML file per metric
│   ├── cdes/                 # One YAML file per critical data element
│   └── sources/              # One YAML file per source system
├── metrica/                  # Python package
│   ├── registry/             # Metric registry models and loader
│   ├── dq/                   # Data quality framework
│   ├── monitoring/           # Alerting and trend detection
│   └── ml_bridge/            # ML feature engineering bridge
├── sql/                      # DDL and migration scripts
└── tests/                    # Test suite
```

## Quick Start

```bash
# Install (Python 3.10+)
pip install -e ".[dev]"

# Run tests
pytest

# Load all definitions
python -c "
from pathlib import Path
from metrica.registry.loader import DefinitionLoader

loader = DefinitionLoader(Path('definitions'))
for m in loader.metrics():
    print(f'{m.metric_id}: {m.name} [{m.domain.value}]')
"
```

## Onboarding a New Metric

1. **Define the source** — create `definitions/sources/<system>.yaml` if the source system doesn't exist yet
2. **Define CDEs** — create `definitions/cdes/<source>_<field>.yaml` for each critical data element
3. **Define the metric** — create `definitions/metrics/<metric_id>.yaml` with:
   - Metric metadata (ID, name, domain, owner, cadence)
   - Source mappings (transformation SQL)
   - Lineage (upstream CDEs, downstream consumers)
   - DQ rules (one per relevant dimension)
4. **Run tests** — `pytest` validates all definitions load correctly
5. **Commit** — all definitions are version-controlled

### Metric YAML Template

```yaml
metric_id: my_new_metric
name: Human Readable Name
description: What this metric measures and why it matters.
domain: usage_behavior  # See Domain enum for options
owner: Team Name
refresh_cadence: daily
data_type: float
unit: count
version: 1
status: active
tags: [churn_feature]

source_mappings:
  - source_system: crm
    source_table: crm_customers
    source_fields: [field_a, field_b]
    transformation: "SELECT ... FROM ..."
    target_table: metrics.customer_metrics
    target_column: my_new_metric

lineage:
  upstream_cdes: [crm.field_a]
  downstream_consumers: [dashboard:overview, ml_feature:my_new_metric]

dq_rules:
  - rule_id: my_new_metric_completeness
    dimension: completeness
    check_expression: "my_new_metric IS NOT NULL"
    warn_threshold: 0.99
    fail_threshold: 0.95
```

## Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language | Python 3.10+ | Primary language, ARM-compatible |
| Data models | Pydantic v2 | Validation, serialization, schema generation |
| Definitions | YAML | Human-readable, git-diffable, no tooling required |
| Analytical DB | DuckDB | Embedded, fast OLAP, zero-dependency, ARM-native |
| DQ metadata | DuckDB | Same engine for DQ score storage and trend queries |
| Scheduling | schedule | Lightweight Python job scheduler for daemon mode |
| SQL DDL | Standard SQL | Compatible with DuckDB and PostgreSQL |

## Running the DQ Scheduler

Metrica includes a DQ scheduler that runs checks automatically. Configuration lives in `dq_schedule.yaml`.

### Manual Run (Single-Shot)

```bash
# Run once and exit — prints scorecard, writes alert on WARN/FAIL
python3 scripts/run_scheduler.py --once

# Dry run — shows what would run without writing to DB or .alerts/
python3 scripts/run_scheduler.py --once --dry-run
```

### Cron Mode (Termux)

Add to `crontab -e` to run every hour:

```
0 * * * * cd /data/data/com.termux/files/home/alex/wrks/metica && .venv/bin/python3 scripts/run_scheduler.py --once >> .logs/dq_cron.log 2>&1
```

### Daemon Mode (Interactive Session)

```bash
# Run every 60 minutes (default from config)
python3 scripts/run_scheduler.py --daemon

# Override interval to every 30 minutes
python3 scripts/run_scheduler.py --daemon --interval 30
```

Press Ctrl+C to stop. Daemon mode is useful during development or active Termux sessions.

### Alert Files

Alerts are written to `.alerts/` as markdown files when DQ checks produce warnings or failures:

```
.alerts/
├── 20260406_140001_WARN.md   # Timestamped alert
└── latest.md                  # Always the most recent run
```

Check the latest DQ status: `cat .alerts/latest.md`

## Pilot Metrics

| Metric | Domain | Source | Description |
|--------|--------|--------|-------------|
| `tenure_months` | Contract & Account | CRM | Months since activation |
| `monthly_charges` | Billing & Financial | Billing | Current monthly charge |
| `support_calls_30d` | Customer Service | Contact Center | Support calls in 30d window |

## First ML Use Case: Customer Churn Prediction

Metrica's first consumer is a churn prediction model with ~40 features spanning usage, billing, contract, service, network, and behavioral domains. Every ML feature traces back to one or more Metrica metrics with DQ gates enforced before training or inference.

For the full end-to-end data flow, see [ARCHITECTURE.md](ARCHITECTURE.md).
