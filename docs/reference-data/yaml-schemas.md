# YAML Schema Reference

All reference data is defined in YAML files under `definitions/reference/`. Each entity type has a specific schema with mandatory and optional fields.

---

## System (`definitions/reference/systems/*.yaml`)

Registers source and target systems in the data landscape.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `system_code` | string | **yes** | Unique identifier (PK). Part of NK in all other entities. |
| `name` | string | **yes** | Human-readable system name. |
| `description` | string | no | Detailed description of the system. |
| `business_domain` | string | **yes** | Business domain (e.g., `customer_management`, `revenue`, `network_operations`). |
| `classification` | string | **yes** | `data_warehouse` or `data_product`. |
| `lifecycle_status` | string | **yes** | `dev`, `prod`, or `decommissioned`. |
| `biz_effective_from` | date | **yes** | When this system record became effective. |
| `biz_effective_to` | date | **yes** | When this system record expires. Use `9999-12-31` for open-ended. |

---

## Code Set (`definitions/reference/code_sets/*.yaml`)

Container that groups related code values. Each code set belongs to one system.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `system_code` | string | **yes** | FK to system. Part of combined NK. |
| `codeset_code` | string | **yes** | Unique within system. Part of combined NK. |
| `name` | string | **yes** | Human-readable code set name. |
| `description` | string | no | Detailed description. |
| `owner_domain` | string | no | Business domain that owns this code set. |
| `biz_effective_from` | date | **yes** | Container-level business effective start. |
| `biz_effective_to` | date | **yes** | Container-level business effective end. |
| `values` | list | **yes** | List of Code Value objects (see below). |

### Code Value (nested in `values[]`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | **yes** | The code value. NK within the code set. |
| `label` | string | no | Human-readable label. |
| `description` | string | no | Detailed description. |
| `biz_effective_from` | date | **yes** | When this code value became effective. |
| `biz_effective_to` | date | **yes** | When this code value expires. |

**Constraint**: No overlapping `biz_effective_from/to` ranges for the same `code` within a code set.

---

## Crosswalk (`definitions/reference/crosswalks/*.yaml`)

Container that maps codes between a source and target system.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_system` | string | **yes** | FK to system (source side). |
| `target_system` | string | **yes** | FK to system (target side). |
| `crosswalk_code` | string | **yes** | Unique within source+target pair. |
| `name` | string | **yes** | Human-readable crosswalk name. |
| `description` | string | no | Detailed description. |
| `mapping_type` | string | **yes** | `one-to-one`, `many-to-one`, or `one-to-many`. |
| `biz_effective_from` | date | **yes** | Container-level business effective start. |
| `biz_effective_to` | date | **yes** | Container-level business effective end. |
| `mappings` | list | **yes** | List of Mapping Value objects (see below). |

### Mapping Value — One-to-One

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_code` | string | **yes** | Source code value. |
| `target_code` | string | **yes** | Target code value. |
| `biz_effective_from` | date | **yes** | When this mapping became effective. |
| `biz_effective_to` | date | **yes** | When this mapping expires. |

### Mapping Value — Many-to-One

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_codes` | list[string] | **yes** | Multiple source codes that map to one target. |
| `target_code` | string | **yes** | Target code value. |
| `biz_effective_from` | date | **yes** | When this mapping became effective. |
| `biz_effective_to` | date | **yes** | When this mapping expires. |

### Mapping Value — One-to-Many (with routing)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_code` | string | **yes** | Source code value. |
| `routing_rules` | list | **yes** | Ordered list of routing rules. |
| `routing_rules[].when` | string | conditional | SQL-like condition (e.g., `source_system = 'app_events'`). |
| `routing_rules[].target_code` | string | **yes** | Target code for this route. |
| `routing_rules[].default` | string | conditional | Fallback target code (use instead of `when`). |
| `biz_effective_from` | date | **yes** | When this mapping became effective. |
| `biz_effective_to` | date | **yes** | When this mapping expires. |

---

## Hierarchy (`definitions/reference/hierarchies/*.yaml`)

Container for a hierarchical tree structure.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `system_code` | string | **yes** | FK to system. |
| `hierarchy_code` | string | **yes** | Unique within system. |
| `name` | string | **yes** | Human-readable hierarchy name. |
| `description` | string | no | Detailed description. |
| `levels` | list[string] | **yes** | Ordered list of level names, root → leaf. |
| `biz_effective_from` | date | **yes** | Container-level business effective start. |
| `biz_effective_to` | date | **yes** | Container-level business effective end. |
| `nodes` | list | **yes** | List of Hierarchy Value objects (see below). |

### Hierarchy Value (nested in `nodes[]`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `node_code` | string | **yes** | Node identifier. NK within hierarchy. |
| `level` | string | **yes** | Which level this node belongs to (from `levels[]`). |
| `parent_code` | string | no | Parent node code. `null` for root nodes. |
| `label` | string | no | Human-readable label. |
| `biz_effective_from` | date | **yes** | When this node assignment became effective. |
| `biz_effective_to` | date | **yes** | When this node assignment expires. |

**Constraint**: Each child has exactly one parent at any given time — no overlapping `biz_effective_from/to` ranges for the same `node_code`.

---

## Bi-Temporal Columns

In YAML files, only **business dates** are authored:
- `biz_effective_from` — when the value is true in the real world
- `biz_effective_to` — when the value stops being true

**System timestamps** (`sys_start_ts`, `sys_end_ts`) are managed automatically by the pipeline when loading YAML into the database.

See [Bi-Temporal SCD2](bi-temporal-scd2.md) for the full temporal design.
