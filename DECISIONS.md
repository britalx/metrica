# Architecture Decisions

Key design decisions made during the Metrica project kickoff, with rationale.

## AD-001: YAML for Metric Definitions (not DB-first)

**Decision**: Store metric, CDE, and source definitions as YAML files in `definitions/`, not directly in a database.

**Rationale**:
- Git-diffable: every change to a metric definition is a versioned commit
- Human-readable: domain experts can review and edit definitions without SQL
- CI/CD friendly: definitions can be validated in pull requests before deployment
- Portable: no database dependency for reading definitions
- The Python loader hydrates these into Pydantic models at runtime, and a separate step can sync them to a DB catalog

**Trade-off**: Slightly more complex than direct DB inserts, but the auditability gains are worth it for a governance system.

## AD-002: DuckDB over SQLite for Analytical Storage

**Decision**: Use DuckDB as the embedded analytical database for DQ scores, trend queries, and metric storage.

**Rationale**:
- Columnar storage is ideal for DQ trend analysis (time-series queries over scores)
- Native ARM support, runs well on Termux
- SQL dialect is richer than SQLite (window functions, INTERVAL types, etc.)
- Can read Parquet/CSV files directly — useful for future data ingestion
- Zero external dependencies (single binary, Python package)

**Trade-off**: DuckDB is less battle-tested than SQLite for write-heavy OLTP workloads, but our DQ scoring is append-mostly analytical — a perfect fit.

## AD-003: Pydantic v2 for Data Models

**Decision**: Use Pydantic v2 for all data models (metrics, CDEs, DQ scores).

**Rationale**:
- Runtime validation: catches malformed definitions early
- Schema generation: can auto-generate JSON Schema for documentation
- Serialization: easy conversion to/from YAML, JSON, dict
- IDE support: full type hints and autocomplete

## AD-004: Custom DQ Framework (not Great Expectations or Soda)

**Decision**: Build a lightweight custom DQ framework instead of using Great Expectations, Soda Core, or dbt tests.

**Rationale**:
- **Great Expectations**: Heavy dependency, JVM-adjacent ecosystem, complex configuration — overkill for embedded use on Termux ARM
- **Soda Core**: Lighter but still requires a Soda Cloud account for full features, and the DSL adds another abstraction layer
- **dbt tests**: Would require dbt itself as a dependency, which brings its own weight
- Custom framework: ~200 lines of Python, DQ rules are stored alongside metric definitions in YAML, scores go to DuckDB. Full control, minimal footprint.

**Trade-off**: We own the maintenance, but the scope is narrow (5 dimensions, threshold-based scoring) and well-understood.

## AD-005: DQ Rules Co-located with Metric Definitions

**Decision**: DQ rules are defined in the same YAML file as the metric they govern, under a `dq_rules` key.

**Rationale**:
- Single source of truth: when you read a metric definition, you see its quality expectations
- No orphaned rules: if a metric is deleted, its DQ rules go with it
- Easy onboarding: adding a new metric means filling out one file

**Trade-off**: For complex cross-metric DQ rules (e.g., consistency between two metrics), we may need a separate `dq_rules/` directory later. The loader already supports this extension.

## AD-006: Metric Lineage in Definitions (not runtime-discovered)

**Decision**: Lineage (upstream CDEs, downstream consumers) is declared in the metric YAML, not auto-discovered from SQL parsing.

**Rationale**:
- Explicit > implicit: declared lineage is always accurate
- No need for SQL parsing infrastructure
- Works for non-SQL transformations too (Python, API-derived metrics)
- Can be validated: CI can check that referenced CDEs actually exist

**Future**: If the SQL layer grows complex, we could add optional auto-discovery as a supplement, but declared lineage remains the authority.

## AD-007: Schema-per-Concern in SQL DDL

**Decision**: Use separate SQL schemas (`metrics.*`, `dq.*`) for different concerns.

**Rationale**:
- Clear separation: metric data vs. DQ metadata vs. operational tables
- Access control ready: when we move to a shared DB, schemas map to permission boundaries
- DuckDB supports schemas natively
