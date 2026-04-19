# User Story: Reference Data YAML Definition Structure

## Title
As a **data engineer**, I want a YAML-based definition structure for managing reference data (systems, code sets, crosswalks, hierarchies) with bi-temporal SCD2 semantics, so that reference data is version-controlled, reviewable via PRs, and serves as the single source of truth for all data mappings.

## Background
Reference data (code sets, crosswalks, hierarchies) is foundational to data integration and quality. In a Data Mesh world, multiple source systems use different codes for the same concepts. Metrica needs a structured, git-managed reference data layer that:
- Treats ref data as code (like enums)
- Supports bi-temporal SCD2 at every level (independent system + business timelines)
- Separates storage (core) from consumption (semantic layer)
- Uses git branches for Candidate/Approved lifecycle (feature → main)

## Scope
This story covers **structure and documentation only** — no mock data, no pipeline integration.

## Requirements

### 1. YAML Definition Structure (`definitions/reference/`)

```
definitions/reference/
├── systems/                  # Source/target system registry
│   ├── crm.yaml
│   ├── billing.yaml
│   └── ...
├── code_sets/                # Code set containers + code values
│   ├── account_status.yaml
│   ├── contract_type.yaml
│   └── ...
├── crosswalks/               # Mapping containers + mapping values
│   ├── billing_status_to_crm_status.yaml
│   └── ...
└── hierarchies/              # Hierarchy containers + hierarchy values
    ├── geography.yaml
    └── ...
```

### 2. Entity Schemas (mandatory fields)

**System** (`definitions/reference/systems/*.yaml`)
- `system_code` (PK, part of NK in all other entities)
- `name`, `description`
- `business_domain` (e.g., customer_management, revenue, network)
- `data_product` or `data_warehouse` classification
- `lifecycle_status`: dev | prod | decommissioned
- `biz_effective_from`, `biz_effective_to`

**Code Set** (`definitions/reference/code_sets/*.yaml`)
- `system_code` + `codeset_code` (combined NK)
- `name`, `description`, `owner_domain`
- `biz_effective_from`, `biz_effective_to` (container-level)
- `values[]`: list of Code Values, each with:
  - `code` (NK within code set)
  - `label`, `description` (optional)
  - `biz_effective_from`, `biz_effective_to` (independent bi-temporal)
  - **Constraint**: no overlapping business date ranges for same NK

**Crosswalk** (`definitions/reference/crosswalks/*.yaml`)
- `source_system` + `target_system` + `crosswalk_code` (combined NK)
- `name`, `description`
- `mapping_type`: one-to-one | many-to-one | one-to-many
- `biz_effective_from`, `biz_effective_to` (container-level)
- `mappings[]`: list of Mapping Values, each with:
  - `source_code` (or `source_codes[]` for many-to-one)
  - `target_code`
  - `biz_effective_from`, `biz_effective_to`
  - For one-to-many: `routing_rules[]` with `when` conditions and `default`

**Hierarchy** (`definitions/reference/hierarchies/*.yaml`)
- `system_code` + `hierarchy_code` (combined NK)
- `name`, `description`
- `levels[]`: ordered list of level names (e.g., region → market → cell)
- `biz_effective_from`, `biz_effective_to` (container-level)
- `nodes[]`: list of Hierarchy Values, each with:
  - `node_code` (NK within hierarchy)
  - `level`, `parent_code` (null for root nodes)
  - `biz_effective_from`, `biz_effective_to`
  - **Constraint**: each child has exactly one parent at any given time (no overlapping parent assignments)

### 3. Bi-Temporal SCD2 Columns (all entities)
Every record in the storage layer carries:
- `sys_start_ts` / `sys_end_ts` — system audit trail (immutable, auto-managed by pipeline)
- `biz_effective_from` / `biz_effective_to` — business timeline (correctable by users)
- In YAML: only `biz_effective_from` / `biz_effective_to` are authored; system timestamps are pipeline-managed

### 4. Semantic Layer Logic (`ref_data_semla`)
- Trims child business date ranges by parent container's date range
- Example: if codeset is effective 2023-01-01 → 2024-12-31, code values are clipped to that window
- Exposes point-in-time views: "give me all valid codes as of date X"
- Validates no overlapping business date ranges for the same NK

### 5. SQL DDL
- `sql/005_ref_data_core.sql`: tables for system, codeset, codevalue, crosswalk, mapping_value, hierarchy, hierarchy_value — all with bi-temporal columns
- `sql/006_ref_data_semla.sql`: views that apply container cut-off logic and expose clean, point-in-time queryable data

### 6. Documentation (`docs/reference-data/`)
- `README.md`: overview of the reference data architecture (core vs semantic layer)
- `yaml-schemas.md`: field-by-field documentation of each YAML entity schema
- `bi-temporal-scd2.md`: explanation of the two temporal dimensions, correction workflow, and overlap constraints
- `examples.md`: annotated examples for each entity type

## Acceptance Criteria
- [ ] YAML schema files exist under `definitions/reference/` with correct mandatory fields
- [ ] At least one example YAML per entity type (system, codeset, crosswalk, hierarchy)
- [ ] SQL DDL creates all 7 core tables with bi-temporal columns
- [ ] SQL views implement semantic layer cut-off logic
- [ ] Documentation covers structure, relationships, layers, and logic
- [ ] YAML validates via a Pydantic model or JSON Schema (optional but preferred)
- [ ] Git PR workflow documented: feature branch = Candidate, main = Approved

## Definition of Done
- [ ] All YAML schemas defined and documented
- [ ] SQL DDL scripts runnable against DuckDB
- [ ] Semantic layer views return correct point-in-time results
- [ ] Docs folder complete with all 4 documents
- [ ] No breaking changes to existing pipeline

## Priority
**High** — foundational for all downstream ref data work

## Estimated Complexity
**Medium-High** — significant design work for 7 entity schemas, SQL DDL, semantic views, and documentation, but no runtime pipeline changes
