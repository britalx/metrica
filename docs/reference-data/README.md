# Reference Data Architecture

Metrica's reference data layer manages the code sets, crosswalks, and hierarchies that enable consistent data integration across multiple source systems.

## Two-Layer Architecture

### Layer 1: `ref_data_core` (Storage Layer)

The storage layer holds the raw, bi-temporal SCD2 records for all reference data entities. Every record carries two independent temporal dimensions:

| Dimension | Columns | Purpose |
|-----------|---------|---------|
| **System** | `sys_start_ts`, `sys_end_ts` | When the record existed in our system (immutable audit trail) |
| **Business** | `biz_effective_from`, `biz_effective_to` | When the value was actually true in the real world (correctable) |

**Key principle**: Business users can fix historical mistakes by inserting a new system record that corrects the business timeline — without altering the system audit trail.

### Layer 2: `ref_data_semla` (Semantic Layer)

The semantic layer provides clean, consumption-ready views that:

1. **Filter** to current system records (`sys_end_ts = '9999-12-31'`)
2. **Trim** child business dates by parent container's date range (cut-off logic)
3. **Expose** point-in-time query capabilities

**Cut-off logic example**: If a codeset is effective `2023-01-01 → 2024-12-31`, but a code value within it says `2022-06-01 → 9999-12-31`, the semantic layer trims the code value to `2023-01-01 → 2024-12-31`.

## Entity Relationships

```
system (1) ──── (N) codeset (1) ──── (N) codevalue
   │
   └─── (N) crosswalk (1) ──── (N) mapping_value
   │         (source_system + target_system)
   │
   └─── (N) hierarchy (1) ──── (N) hierarchy_value
```

- **system** is the root entity; its `system_code` is part of the Natural Key (NK) in all other tables
- **codeset** → **codevalue**: container → child relationship
- **crosswalk** → **mapping_value**: container → child relationship
- **hierarchy** → **hierarchy_value**: container → child (tree nodes)

## Version Control & Approval Workflow

Reference data is treated as code:

- **YAML definitions** in `definitions/reference/` are the source of truth
- **Feature branch** = Candidate state (proposed changes under review)
- **Merged to main** = Approved state (live in production)
- **Pull Requests** provide review trail and change tracking

## File Structure

```
definitions/reference/
├── systems/           # Source/target system registry
├── code_sets/         # Code set containers + code values
├── crosswalks/        # Mapping containers + mapping values
└── hierarchies/       # Hierarchy containers + hierarchy values

sql/
├── 005_ref_data_core.sql    # Storage layer DDL (7 tables)
└── 006_ref_data_semla.sql   # Semantic layer views (7 views)

docs/reference-data/
├── README.md                # This file
├── yaml-schemas.md          # Field-by-field YAML schema docs
├── bi-temporal-scd2.md      # Bi-temporal design explained
└── examples.md              # Annotated examples
```

## Related Documentation

- [YAML Schemas](yaml-schemas.md) — field-by-field documentation
- [Bi-Temporal SCD2](bi-temporal-scd2.md) — temporal design explained
- [Examples](examples.md) — annotated examples for each entity type
