# User Story: Mock Reference Data from Existing Sources

## Title
As a **data engineer**, I want realistic mock reference data derived from Metrica's existing 6 source systems, so that I can validate the reference data structure, test crosswalk mappings, and demonstrate how multi-source code translation works end-to-end.

## Background
Metrica has 6 source systems (CRM, Billing, Contact Center, CDR, Network, App Events) each using their own code values for overlapping concepts. In a realistic telecom scenario, these systems were built independently and use different codes for the same business concepts. This story creates mock reference data that:
- Registers all 6 source systems plus a unified target system
- Extracts code values already embedded in mock data generators
- Creates crosswalks to translate between source-specific codes and a canonical target
- Builds at least one hierarchy (geography/network coverage)

## Scope
This story creates **mock YAML files only** — populating the structure defined in the ref data YAML structure story. No pipeline integration.

## Requirements

### 1. System Registry
Register all source systems and one target system:

| system_code | name | business_domain | lifecycle_status |
|-------------|------|-----------------|------------------|
| `crm` | CRM System | customer_management | prod |
| `billing` | Billing System | revenue | prod |
| `contact_center` | Contact Center | customer_support | prod |
| `cdr` | CDR Platform | network_usage | prod |
| `network` | Network Ops | network_operations | prod |
| `app_events` | Mobile App | digital_channels | prod |
| `metrica_unified` | Metrica Unified | analytics | prod |

### 2. Code Sets to Extract from Existing Mock Data

Scan `scripts/generate_mock_data.py` and existing CDEs for embedded code values:

| Code Set | Source System | Values in Mock Data |
|----------|--------------|---------------------|
| `account_status` | crm | active, suspended, terminated |
| `contract_type` | crm | month_to_month, one_year, two_year |
| `interaction_type` | contact_center | call, chat, email |
| `ticket_resolution` | contact_center | resolved, pending, escalated |
| `call_type` | cdr | voice, data, sms |
| `app_event_type` | app_events | login, view_bill, pay_bill, speed_test, change_plan |
| `churn_label` | metrica_unified | 0 (active), 1 (churned) |

Additionally, create **variant code values** for different source systems to demonstrate crosswalk need:
- Billing system uses: `ACTIVE`, `SUSP`, `TERM` (different from CRM's lowercase values)
- Contact center uses: `PHONE`, `ONLINE_CHAT`, `EMAIL_TICKET` (different from its own lowercase values)
- This simulates real-world code divergence across systems

### 3. Crosswalks

Create at least 3 crosswalks demonstrating all mapping types:

**One-to-One**: `billing_account_status_to_crm`
- `ACTIVE` → `active`, `SUSP` → `suspended`, `TERM` → `terminated`

**Many-to-One**: `interaction_type_to_channel`
- `[call, PHONE]` → `voice_channel`
- `[chat, ONLINE_CHAT]` → `digital_channel`
- `[email, EMAIL_TICKET]` → `digital_channel`

**One-to-Many (with routing)**: `app_event_to_activity_category`
- `login`:
  - when `source_system = 'app_events'` → `authentication`
  - when `source_system = 'crm'` → `account_access`
  - default: `unknown_login`

### 4. Hierarchies

Create at least 1 hierarchy:

**Network Coverage Hierarchy** (`network_coverage`):
```
region (Level 1)
├── market (Level 2)
│   ├── cell_sector (Level 3)
```

Example nodes:
- NORTHEAST → NYC_METRO → CELL_001, CELL_002
- NORTHEAST → BOSTON → CELL_010
- SOUTHEAST → MIAMI → CELL_020
- WEST → LA_METRO → CELL_030, CELL_031

Include at least one reparenting example (node moved from one parent to another with different business effective dates).

### 5. Bi-Temporal Examples

Include at least 2 examples of bi-temporal corrections:
1. **Code value correction**: A code value's business effective date was wrong and gets corrected (two YAML records for the same code, different `biz_effective_from`)
2. **Hierarchy reparenting**: A cell sector moves from one market to another (two records with different parents and non-overlapping business date ranges)

## Acceptance Criteria
- [ ] All 7 systems registered in `definitions/reference/systems/`
- [ ] At least 7 code sets created with values from existing mock data
- [ ] At least 2 variant code sets showing cross-system divergence
- [ ] 3 crosswalks created (one-to-one, many-to-one, one-to-many with routing)
- [ ] 1 hierarchy with at least 3 levels and 10+ nodes
- [ ] 2+ bi-temporal correction examples included
- [ ] All YAML files conform to the schema defined in the structure story
- [ ] README in `definitions/reference/` listing all mock ref data files

## Definition of Done
- [ ] All YAML files created under `definitions/reference/`
- [ ] Files pass schema validation (if Pydantic models exist from structure story)
- [ ] SQL load script can ingest YAML into `ref_data_core` tables
- [ ] Semantic layer views return correct results for mock data
- [ ] Cross-system code translation demonstrated end-to-end (source code → crosswalk → target code)

## Dependencies
- Depends on: **User Story: Reference Data YAML Definition Structure** (for schema)
- Parallel work possible: YAML files can be drafted before schema is finalized, then validated after

## Priority
**High** — validates the structure story and provides test data for pipeline integration

## Estimated Complexity
**Medium** — primarily content creation (YAML authoring), leveraging existing mock data patterns, with some design work for crosswalk routing rules


---
## Agent Response (2026-04-19 19:51:21)
**Outcome**: completed

Implemented mock reference data from existing sources: added churn_label + cc_internal_interaction_type code sets (now 9 total), created YAML-to-DuckDB loader script (scripts/load_ref_data.py), loaded 80 records into ref_data_core, verified all 7 semantic layer views. Cross-system translation demo confirmed: billing ACTIVE→crm active (1:1), PHONE→voice_channel (N:1), login→authentication with routing (1:N). Hierarchy point-in-time verified: CELL_005 parent=BOSTON on 2022-12-01, parent=NYC_METRO on 2024-01-01. 80/80 tests pass.
