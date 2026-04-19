# Bi-Temporal SCD2 Design

## Overview

Every reference data record in Metrica carries **two independent temporal dimensions**:

| Dimension | Columns | Managed by | Mutable? |
|-----------|---------|------------|----------|
| **System time** | `sys_start_ts`, `sys_end_ts` | Pipeline (automatic) | No — immutable audit trail |
| **Business time** | `biz_effective_from`, `biz_effective_to` | YAML authors (manual) | Yes — correctable |

This design allows business users to fix historical data without destroying the audit trail.

## How It Works

### System Timeline (Audit)

When a YAML file is loaded into the database:
1. The loader checks if a record with the same Natural Key (NK) already exists
2. If a change is detected, the existing record's `sys_end_ts` is set to `CURRENT_TIMESTAMP`
3. A new record is inserted with `sys_start_ts = CURRENT_TIMESTAMP` and `sys_end_ts = '9999-12-31'`

The system timeline is **append-only** — old records are never deleted or modified (except closing `sys_end_ts`).

### Business Timeline (Reality)

Business dates represent when something was **actually true in the real world**:
- `biz_effective_from`: the date the value became valid
- `biz_effective_to`: the date the value stopped being valid (`9999-12-31` = still valid)

Business dates are authored in YAML and can be **corrected** — if a mistake is discovered, the YAML is updated and reloaded, creating a new system record.

## Correction Workflow

### Example: Fixing a wrong effective date

A code value "HYBRID" was initially recorded as effective from 2023-06-01, but it actually launched on 2023-01-01.

**Step 1**: Original YAML (committed in January 2024)
```yaml
values:
  - code: HYBRID
    label: Hybrid Plan
    biz_effective_from: "2023-06-01"   # WRONG
    biz_effective_to: "9999-12-31"
```

**Database state after initial load:**

| code | biz_effective_from | biz_effective_to | sys_start_ts | sys_end_ts |
|------|-------------------|-----------------|-------------|-----------|
| HYBRID | 2023-06-01 | 9999-12-31 | 2024-01-15 10:00:00 | 9999-12-31 |

**Step 2**: YAML corrected (committed in March 2024)
```yaml
values:
  - code: HYBRID
    label: Hybrid Plan
    biz_effective_from: "2023-01-01"   # CORRECTED
    biz_effective_to: "9999-12-31"
```

**Database state after correction:**

| code | biz_effective_from | biz_effective_to | sys_start_ts | sys_end_ts |
|------|-------------------|-----------------|-------------|-----------|
| HYBRID | 2023-06-01 | 9999-12-31 | 2024-01-15 10:00:00 | **2024-03-20 14:30:00** |
| HYBRID | **2023-01-01** | 9999-12-31 | **2024-03-20 14:30:00** | 9999-12-31 |

**What happened**:
- The old record's system time was closed (`sys_end_ts` set to correction time)
- A new record was created with the corrected business date
- Both records are preserved — full audit trail

## Overlap Constraints

### Business Date Overlap Rule

For any given Natural Key, **business date ranges must not overlap**:

```
NK = (system_code='crm', codeset_code='account_status', code='active')

VALID:
  Record 1: biz_effective_from=2015-01-01, biz_effective_to=2023-12-31
  Record 2: biz_effective_from=2024-01-01, biz_effective_to=9999-12-31

INVALID:
  Record 1: biz_effective_from=2015-01-01, biz_effective_to=2024-06-30  ← overlaps!
  Record 2: biz_effective_from=2024-01-01, biz_effective_to=9999-12-31  ← overlaps!
```

This constraint ensures that at any point in business time, there is at most **one valid value** for each NK.

### Hierarchy Single-Parent Rule

For hierarchy nodes, the overlap constraint also enforces the single-parent rule:
- A node cannot have two parents at the same time
- Reparenting is modeled as two records with non-overlapping business dates

## Semantic Layer Cut-Off

The semantic layer (`ref_data_semla`) applies **container cut-off logic**:

```
Container (codeset):    biz_effective_from=2023-01-01, biz_effective_to=2024-12-31
Child (codevalue):      biz_effective_from=2022-06-01, biz_effective_to=9999-12-31

Semantic layer output:  biz_effective_from=2023-01-01, biz_effective_to=2024-12-31
                        (trimmed to container's range)
```

This ensures consumers never see child records that extend beyond their parent container's validity window.

## Point-in-Time Queries

The semantic layer views support point-in-time filtering:

```sql
-- All valid code values as of June 15, 2023
SELECT * FROM ref_data_semla.v_codevalues
WHERE DATE '2023-06-15' BETWEEN biz_effective_from AND biz_effective_to;

-- Account status codes valid today
SELECT * FROM ref_data_semla.v_codevalues
WHERE codeset_code = 'account_status'
  AND CURRENT_DATE BETWEEN biz_effective_from AND biz_effective_to;

-- Network hierarchy as of a specific date
SELECT * FROM ref_data_semla.v_hierarchy_values
WHERE hierarchy_code = 'network_coverage'
  AND DATE '2022-12-01' BETWEEN biz_effective_from AND biz_effective_to;
```

## Git Integration

The bi-temporal design integrates with git's version control:

| Git State | Reference Data State |
|-----------|---------------------|
| Feature branch | **Candidate** — proposed changes under review |
| Pull Request | Review and approval process |
| Merged to main | **Approved** — live in production |
| Git history | Change audit trail (complements system timestamps) |

Git provides a **third temporal dimension** (commit history) that tracks *who* changed *what* and *when* at the file level.
