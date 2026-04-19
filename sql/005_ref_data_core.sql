-- =============================================================================
-- 005_ref_data_core.sql
-- Reference Data Core Storage Layer
--
-- All 7 entity tables with bi-temporal SCD2 columns:
--   sys_start_ts / sys_end_ts    — immutable system audit trail
--   biz_effective_from / biz_effective_to — correctable business timeline
--
-- Natural Keys (NK) are enforced via unique constraints on NK + sys_end_ts.
-- Business date ranges must not overlap for the same NK (enforced in app layer).
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ref_data_core;

-- Sequences (must exist before tables that reference them)
CREATE SEQUENCE IF NOT EXISTS ref_data_core.system_seq START 1;
CREATE SEQUENCE IF NOT EXISTS ref_data_core.codeset_seq START 1;
CREATE SEQUENCE IF NOT EXISTS ref_data_core.codevalue_seq START 1;
CREATE SEQUENCE IF NOT EXISTS ref_data_core.crosswalk_seq START 1;
CREATE SEQUENCE IF NOT EXISTS ref_data_core.mapping_value_seq START 1;
CREATE SEQUENCE IF NOT EXISTS ref_data_core.hierarchy_seq START 1;
CREATE SEQUENCE IF NOT EXISTS ref_data_core.hierarchy_value_seq START 1;

-- -----------------------------------------------------------------------------
-- 1. system — Source/target system registry
-- NK: system_code
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ref_data_core.system (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('ref_data_core.system_seq'),
    system_code         VARCHAR NOT NULL,
    name                VARCHAR NOT NULL,
    description         VARCHAR,
    business_domain     VARCHAR NOT NULL,
    classification      VARCHAR NOT NULL,  -- 'data_warehouse' | 'data_product'
    lifecycle_status    VARCHAR NOT NULL,  -- 'dev' | 'prod' | 'decommissioned'
    biz_effective_from  DATE NOT NULL,
    biz_effective_to    DATE NOT NULL DEFAULT '9999-12-31',
    sys_start_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_end_ts          TIMESTAMP NOT NULL DEFAULT '9999-12-31 00:00:00'
);

-- -----------------------------------------------------------------------------
-- 2. codeset — Code set container
-- NK: system_code + codeset_code
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ref_data_core.codeset (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('ref_data_core.codeset_seq'),
    system_code         VARCHAR NOT NULL,
    codeset_code        VARCHAR NOT NULL,
    name                VARCHAR NOT NULL,
    description         VARCHAR,
    owner_domain        VARCHAR,
    biz_effective_from  DATE NOT NULL,
    biz_effective_to    DATE NOT NULL DEFAULT '9999-12-31',
    sys_start_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_end_ts          TIMESTAMP NOT NULL DEFAULT '9999-12-31 00:00:00'
);

-- -----------------------------------------------------------------------------
-- 3. codevalue — Individual values within a code set
-- NK: system_code + codeset_code + code
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ref_data_core.codevalue (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('ref_data_core.codevalue_seq'),
    system_code         VARCHAR NOT NULL,
    codeset_code        VARCHAR NOT NULL,
    code                VARCHAR NOT NULL,
    label               VARCHAR,
    description         VARCHAR,
    biz_effective_from  DATE NOT NULL,
    biz_effective_to    DATE NOT NULL DEFAULT '9999-12-31',
    sys_start_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_end_ts          TIMESTAMP NOT NULL DEFAULT '9999-12-31 00:00:00'
);

-- -----------------------------------------------------------------------------
-- 4. crosswalk — Mapping container
-- NK: source_system + target_system + crosswalk_code
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ref_data_core.crosswalk (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('ref_data_core.crosswalk_seq'),
    source_system       VARCHAR NOT NULL,
    target_system       VARCHAR NOT NULL,
    crosswalk_code      VARCHAR NOT NULL,
    name                VARCHAR NOT NULL,
    description         VARCHAR,
    mapping_type        VARCHAR NOT NULL,  -- 'one-to-one' | 'many-to-one' | 'one-to-many'
    biz_effective_from  DATE NOT NULL,
    biz_effective_to    DATE NOT NULL DEFAULT '9999-12-31',
    sys_start_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_end_ts          TIMESTAMP NOT NULL DEFAULT '9999-12-31 00:00:00'
);

-- -----------------------------------------------------------------------------
-- 5. mapping_value — Individual mapping entries within a crosswalk
-- NK: source_system + target_system + crosswalk_code + source_code + target_code
-- For many-to-one: multiple rows with different source_code, same target_code
-- For one-to-many: multiple rows with same source_code, different target_code
--                  + routing_condition to disambiguate
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ref_data_core.mapping_value (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('ref_data_core.mapping_value_seq'),
    source_system       VARCHAR NOT NULL,
    target_system       VARCHAR NOT NULL,
    crosswalk_code      VARCHAR NOT NULL,
    source_code         VARCHAR NOT NULL,
    target_code         VARCHAR NOT NULL,
    routing_condition   VARCHAR,  -- CASE WHEN expression for one-to-many routing
    is_default          BOOLEAN DEFAULT FALSE,  -- default route for one-to-many
    biz_effective_from  DATE NOT NULL,
    biz_effective_to    DATE NOT NULL DEFAULT '9999-12-31',
    sys_start_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_end_ts          TIMESTAMP NOT NULL DEFAULT '9999-12-31 00:00:00'
);

-- -----------------------------------------------------------------------------
-- 6. hierarchy — Hierarchy container
-- NK: system_code + hierarchy_code
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ref_data_core.hierarchy (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('ref_data_core.hierarchy_seq'),
    system_code         VARCHAR NOT NULL,
    hierarchy_code      VARCHAR NOT NULL,
    name                VARCHAR NOT NULL,
    description         VARCHAR,
    levels              VARCHAR NOT NULL,  -- JSON array of level names, ordered root→leaf
    biz_effective_from  DATE NOT NULL,
    biz_effective_to    DATE NOT NULL DEFAULT '9999-12-31',
    sys_start_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_end_ts          TIMESTAMP NOT NULL DEFAULT '9999-12-31 00:00:00'
);

-- -----------------------------------------------------------------------------
-- 7. hierarchy_value — Nodes in the hierarchy tree
-- NK: system_code + hierarchy_code + node_code
-- Constraint: each child has exactly one parent at any given time
--             (non-overlapping biz_effective_from/to for same NK)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ref_data_core.hierarchy_value (
    id                  INTEGER PRIMARY KEY DEFAULT nextval('ref_data_core.hierarchy_value_seq'),
    system_code         VARCHAR NOT NULL,
    hierarchy_code      VARCHAR NOT NULL,
    node_code           VARCHAR NOT NULL,
    label               VARCHAR,
    level               VARCHAR NOT NULL,
    parent_code         VARCHAR,  -- NULL for root nodes
    biz_effective_from  DATE NOT NULL,
    biz_effective_to    DATE NOT NULL DEFAULT '9999-12-31',
    sys_start_ts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sys_end_ts          TIMESTAMP NOT NULL DEFAULT '9999-12-31 00:00:00'
);
