# Reference Data — Mock Data Inventory

This directory contains all reference data YAML definitions for Metrica's 6 source systems plus the unified analytics target. These files are the **source of truth** for code sets, crosswalks, and hierarchies.

## Systems (`systems/`)

| File | system_code | Business Domain | Status |
|------|-------------|-----------------|--------|
| [crm.yaml](systems/crm.yaml) | `crm` | customer_management | prod |
| [billing.yaml](systems/billing.yaml) | `billing` | revenue | prod |
| [contact_center.yaml](systems/contact_center.yaml) | `contact_center` | customer_support | prod |
| [cdr.yaml](systems/cdr.yaml) | `cdr` | network_usage | prod |
| [network.yaml](systems/network.yaml) | `network` | network_operations | prod |
| [app_events.yaml](systems/app_events.yaml) | `app_events` | digital_channels | prod |
| [metrica_unified.yaml](systems/metrica_unified.yaml) | `metrica_unified` | analytics | prod |

## Code Sets (`code_sets/`)

| File | System | Codeset Code | # Values | Notes |
|------|--------|-------------|----------|-------|
| [account_status.yaml](code_sets/account_status.yaml) | crm | `account_status` | 3 | active, suspended, terminated |
| [contract_type.yaml](code_sets/contract_type.yaml) | crm | `contract_type` | 3 | month_to_month, one_year, two_year |
| [interaction_type.yaml](code_sets/interaction_type.yaml) | contact_center | `interaction_type` | 3 | call, chat, email |
| [cc_internal_interaction_type.yaml](code_sets/cc_internal_interaction_type.yaml) | contact_center | `cc_internal_interaction_type` | 3 | PHONE, ONLINE_CHAT, EMAIL_TICKET (**variant**) |
| [ticket_resolution.yaml](code_sets/ticket_resolution.yaml) | contact_center | `ticket_resolution` | 3 | resolved, pending, escalated |
| [call_type.yaml](code_sets/call_type.yaml) | cdr | `call_type` | 3 | voice, data, sms |
| [app_event_type.yaml](code_sets/app_event_type.yaml) | app_events | `app_event_type` | 5 | login, view_bill, pay_bill, speed_test, change_plan |
| [billing_account_status.yaml](code_sets/billing_account_status.yaml) | billing | `billing_account_status` | 3 | ACTIVE, SUSP, TERM (**variant**) |
| [churn_label.yaml](code_sets/churn_label.yaml) | metrica_unified | `churn_label` | 2 | 0 (active), 1 (churned) |

**Variant code sets** demonstrate cross-system code divergence — the same business concept is represented differently across systems. Crosswalks translate between them.

## Crosswalks (`crosswalks/`)

| File | Source → Target | Type | # Mappings |
|------|----------------|------|-----------|
| [billing_status_to_crm_status.yaml](crosswalks/billing_status_to_crm_status.yaml) | billing → crm | one-to-one | 3 |
| [interaction_type_to_channel.yaml](crosswalks/interaction_type_to_channel.yaml) | contact_center → metrica_unified | many-to-one | 3 |
| [app_event_to_activity_category.yaml](crosswalks/app_event_to_activity_category.yaml) | app_events → metrica_unified | one-to-many | 3 |

## Hierarchies (`hierarchies/`)

| File | System | Hierarchy Code | Levels | # Nodes |
|------|--------|---------------|--------|---------|
| [network_coverage.yaml](hierarchies/network_coverage.yaml) | network | `network_coverage` | region → market → cell_sector | 14 |

Includes **reparenting example**: CELL_005 moved from BOSTON to NYC_METRO on 2023-07-01.

## Bi-Temporal Examples

1. **Hierarchy reparenting** — `network_coverage.yaml`, node CELL_005: two records with non-overlapping business dates showing movement between parents
2. **Code value correction** — demonstrated in documentation (`docs/reference-data/examples.md`): `speed_test` business effective date corrected from 2020-06-01 to 2020-03-15

## Validation

All YAML files pass Pydantic schema validation:

```bash
python -c "
import yaml
from pathlib import Path
from metrica.registry.ref_models import (
    SystemDefinition, CodeSetDefinition, CrosswalkDefinition, HierarchyDefinition
)

for f in Path('definitions/reference/systems').glob('*.yaml'):
    SystemDefinition(**yaml.safe_load(f.read_text()))
for f in Path('definitions/reference/code_sets').glob('*.yaml'):
    CodeSetDefinition(**yaml.safe_load(f.read_text()))
for f in Path('definitions/reference/crosswalks').glob('*.yaml'):
    CrosswalkDefinition(**yaml.safe_load(f.read_text()))
for f in Path('definitions/reference/hierarchies').glob('*.yaml'):
    HierarchyDefinition(**yaml.safe_load(f.read_text()))
print('All files valid')
"
```

## Related

- [Architecture Overview](../../docs/reference-data/README.md)
- [YAML Schema Reference](../../docs/reference-data/yaml-schemas.md)
- [Bi-Temporal SCD2 Design](../../docs/reference-data/bi-temporal-scd2.md)
- [Annotated Examples](../../docs/reference-data/examples.md)
