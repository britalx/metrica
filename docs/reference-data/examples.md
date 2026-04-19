# Reference Data Examples

Annotated examples for each entity type, showing real-world usage patterns.

---

## 1. System Registration

```yaml
# definitions/reference/systems/crm.yaml
system_code: crm
name: CRM System
description: >
  Primary customer relationship management system.
business_domain: customer_management
classification: data_warehouse
lifecycle_status: prod
biz_effective_from: "2015-01-01"
biz_effective_to: "9999-12-31"
```

**Key points**:
- `system_code` becomes part of the NK in all other entities
- `classification` distinguishes traditional data warehouses from modern data products
- `lifecycle_status` tracks whether the system is active in production

---

## 2. Code Set with Values

```yaml
# definitions/reference/code_sets/account_status.yaml
system_code: crm
codeset_code: account_status
name: Account Status
description: Customer account lifecycle status.
owner_domain: customer_management
biz_effective_from: "2015-01-01"
biz_effective_to: "9999-12-31"

values:
  - code: active
    label: Active
    biz_effective_from: "2015-01-01"
    biz_effective_to: "9999-12-31"

  - code: suspended
    label: Suspended
    biz_effective_from: "2015-01-01"
    biz_effective_to: "9999-12-31"

  - code: terminated
    label: Terminated
    biz_effective_from: "2015-01-01"
    biz_effective_to: "9999-12-31"
```

**Key points**:
- Combined NK: `system_code` + `codeset_code`
- Each code value has its own independent business dates
- The semantic layer will trim code value dates by the codeset's date range

---

## 3. Cross-System Code Divergence

Different systems often use different codes for the same concept:

| Concept | CRM System | Billing System |
|---------|-----------|---------------|
| Active | `active` | `ACTIVE` |
| Suspended | `suspended` | `SUSP` |
| Terminated | `terminated` | `TERM` |

This is why crosswalks are needed — to translate between systems.

---

## 4. Crosswalk — One-to-One

```yaml
# definitions/reference/crosswalks/billing_status_to_crm_status.yaml
source_system: billing
target_system: crm
crosswalk_code: billing_status_to_crm_status
name: Billing Account Status to CRM Status
mapping_type: one-to-one
biz_effective_from: "2015-01-01"
biz_effective_to: "9999-12-31"

mappings:
  - source_code: ACTIVE
    target_code: active
    biz_effective_from: "2015-01-01"
    biz_effective_to: "9999-12-31"

  - source_code: SUSP
    target_code: suspended
    biz_effective_from: "2015-01-01"
    biz_effective_to: "9999-12-31"

  - source_code: TERM
    target_code: terminated
    biz_effective_from: "2015-01-01"
    biz_effective_to: "9999-12-31"
```

**SQL lookup**:
```sql
SELECT target_code
FROM ref_data_semla.v_mapping_values
WHERE crosswalk_code = 'billing_status_to_crm_status'
  AND source_code = 'ACTIVE'
  AND CURRENT_DATE BETWEEN biz_effective_from AND biz_effective_to;
-- Returns: 'active'
```

---

## 5. Crosswalk — Many-to-One

```yaml
# definitions/reference/crosswalks/interaction_type_to_channel.yaml
source_system: contact_center
target_system: metrica_unified
crosswalk_code: interaction_type_to_channel
mapping_type: many-to-one
biz_effective_from: "2016-03-01"
biz_effective_to: "9999-12-31"

mappings:
  - source_codes: [call, PHONE]
    target_code: voice_channel
    biz_effective_from: "2016-03-01"
    biz_effective_to: "9999-12-31"

  - source_codes: [chat, ONLINE_CHAT]
    target_code: digital_channel
    biz_effective_from: "2018-06-01"
    biz_effective_to: "9999-12-31"
```

**Note**: In the database, each source code becomes a separate `mapping_value` row pointing to the same `target_code`.

---

## 6. Crosswalk — One-to-Many with Routing

```yaml
# definitions/reference/crosswalks/app_event_to_activity_category.yaml
source_system: app_events
target_system: metrica_unified
crosswalk_code: app_event_to_activity_category
mapping_type: one-to-many
biz_effective_from: "2020-01-15"
biz_effective_to: "9999-12-31"

mappings:
  - source_code: login
    routing_rules:
      - when: "source_system = 'app_events'"
        target_code: authentication
      - when: "source_system = 'crm'"
        target_code: account_access
      - default: unknown_login
    biz_effective_from: "2020-01-15"
    biz_effective_to: "9999-12-31"
```

**SQL lookup with routing**:
```sql
SELECT target_code
FROM ref_data_semla.v_mapping_values
WHERE crosswalk_code = 'app_event_to_activity_category'
  AND source_code = 'login'
  AND (routing_condition = 'source_system = ''app_events''' OR is_default = TRUE)
  AND CURRENT_DATE BETWEEN biz_effective_from AND biz_effective_to
ORDER BY is_default ASC
LIMIT 1;
-- Returns: 'authentication'
```

---

## 7. Hierarchy with Reparenting

```yaml
# definitions/reference/hierarchies/network_coverage.yaml
system_code: network
hierarchy_code: network_coverage
name: Network Coverage Hierarchy
levels: [region, market, cell_sector]
biz_effective_from: "2017-06-01"
biz_effective_to: "9999-12-31"

nodes:
  # CELL_005 was originally under BOSTON, then moved to NYC_METRO
  - node_code: CELL_005
    level: cell_sector
    parent_code: BOSTON
    label: Connecticut Border Sector
    biz_effective_from: "2019-01-01"
    biz_effective_to: "2023-06-30"       # Ended when reparented

  - node_code: CELL_005
    level: cell_sector
    parent_code: NYC_METRO               # New parent
    label: Connecticut Border Sector
    biz_effective_from: "2023-07-01"     # Starts after old record ends
    biz_effective_to: "9999-12-31"
```

**Key points**:
- Same `node_code` appears twice with **non-overlapping** business date ranges
- Before 2023-07-01: CELL_005 → BOSTON → NORTHEAST
- After 2023-07-01: CELL_005 → NYC_METRO → NORTHEAST
- The bi-temporal design captures both states without losing history

**Point-in-time queries**:
```sql
-- Where was CELL_005 on 2022-12-01?
SELECT parent_code FROM ref_data_semla.v_hierarchy_values
WHERE node_code = 'CELL_005'
  AND DATE '2022-12-01' BETWEEN biz_effective_from AND biz_effective_to;
-- Returns: BOSTON

-- Where is CELL_005 today?
SELECT parent_code FROM ref_data_semla.v_hierarchy_values
WHERE node_code = 'CELL_005'
  AND CURRENT_DATE BETWEEN biz_effective_from AND biz_effective_to;
-- Returns: NYC_METRO
```

---

## 8. Bi-Temporal Correction Example

A code value's effective date was recorded incorrectly and needs correction.

**Before correction** (in git history):
```yaml
values:
  - code: speed_test
    label: Speed Test
    biz_effective_from: "2020-06-01"    # Originally recorded
    biz_effective_to: "9999-12-31"
```

**After correction** (current YAML):
```yaml
values:
  - code: speed_test
    label: Speed Test
    biz_effective_from: "2020-03-15"    # Corrected — launched earlier
    biz_effective_to: "9999-12-31"
```

**Database shows both versions** via system timestamps:

| code | biz_effective_from | sys_start_ts | sys_end_ts |
|------|-------------------|-------------|-----------|
| speed_test | 2020-06-01 | 2024-01-10 | 2024-05-20 |
| speed_test | 2020-03-15 | 2024-05-20 | 9999-12-31 |

The correction is fully traceable: git history shows the YAML change, and the database shows the system timeline.
