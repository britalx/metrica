-- =============================================================================
-- 006_ref_data_semla.sql
-- Reference Data Semantic Layer (SEMLA)
--
-- Views that apply container cut-off logic and expose clean, point-in-time
-- queryable data. The semantic layer:
--   1. Filters to current system records (sys_end_ts = '9999-12-31')
--   2. Trims child business dates by parent container's date range
--   3. Provides point-in-time query helpers
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ref_data_semla;

-- -----------------------------------------------------------------------------
-- Current Systems — only active system records
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ref_data_semla.v_systems AS
SELECT
    system_code,
    name,
    description,
    business_domain,
    classification,
    lifecycle_status,
    biz_effective_from,
    biz_effective_to,
    sys_start_ts,
    sys_end_ts
FROM ref_data_core.system
WHERE sys_end_ts = '9999-12-31 00:00:00';

-- -----------------------------------------------------------------------------
-- Current Code Sets — only active codeset records
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ref_data_semla.v_codesets AS
SELECT
    cs.system_code,
    cs.codeset_code,
    cs.name,
    cs.description,
    cs.owner_domain,
    cs.biz_effective_from,
    cs.biz_effective_to,
    cs.sys_start_ts
FROM ref_data_core.codeset cs
WHERE cs.sys_end_ts = '9999-12-31 00:00:00';

-- -----------------------------------------------------------------------------
-- Current Code Values — with container cut-off applied
--
-- Business dates of code values are trimmed by their parent codeset's range:
--   effective_from = MAX(codevalue.biz_effective_from, codeset.biz_effective_from)
--   effective_to   = MIN(codevalue.biz_effective_to,   codeset.biz_effective_to)
-- Only returns rows where the trimmed range is valid (from <= to).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ref_data_semla.v_codevalues AS
SELECT
    cv.system_code,
    cv.codeset_code,
    cv.code,
    cv.label,
    cv.description,
    -- Trimmed business dates (cut-off by parent codeset)
    GREATEST(cv.biz_effective_from, cs.biz_effective_from) AS biz_effective_from,
    LEAST(cv.biz_effective_to, cs.biz_effective_to)       AS biz_effective_to,
    -- Original dates for audit
    cv.biz_effective_from AS raw_biz_effective_from,
    cv.biz_effective_to   AS raw_biz_effective_to,
    cv.sys_start_ts
FROM ref_data_core.codevalue cv
JOIN ref_data_core.codeset cs
    ON cv.system_code = cs.system_code
    AND cv.codeset_code = cs.codeset_code
    AND cs.sys_end_ts = '9999-12-31 00:00:00'
WHERE cv.sys_end_ts = '9999-12-31 00:00:00'
  AND GREATEST(cv.biz_effective_from, cs.biz_effective_from)
      <= LEAST(cv.biz_effective_to, cs.biz_effective_to);

-- -----------------------------------------------------------------------------
-- Current Crosswalks — only active crosswalk records
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ref_data_semla.v_crosswalks AS
SELECT
    cw.source_system,
    cw.target_system,
    cw.crosswalk_code,
    cw.name,
    cw.description,
    cw.mapping_type,
    cw.biz_effective_from,
    cw.biz_effective_to,
    cw.sys_start_ts
FROM ref_data_core.crosswalk cw
WHERE cw.sys_end_ts = '9999-12-31 00:00:00';

-- -----------------------------------------------------------------------------
-- Current Mapping Values — with container cut-off applied
--
-- Business dates of mappings are trimmed by their parent crosswalk's range.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ref_data_semla.v_mapping_values AS
SELECT
    mv.source_system,
    mv.target_system,
    mv.crosswalk_code,
    mv.source_code,
    mv.target_code,
    mv.routing_condition,
    mv.is_default,
    -- Trimmed business dates
    GREATEST(mv.biz_effective_from, cw.biz_effective_from) AS biz_effective_from,
    LEAST(mv.biz_effective_to, cw.biz_effective_to)       AS biz_effective_to,
    mv.biz_effective_from AS raw_biz_effective_from,
    mv.biz_effective_to   AS raw_biz_effective_to,
    mv.sys_start_ts
FROM ref_data_core.mapping_value mv
JOIN ref_data_core.crosswalk cw
    ON mv.source_system = cw.source_system
    AND mv.target_system = cw.target_system
    AND mv.crosswalk_code = cw.crosswalk_code
    AND cw.sys_end_ts = '9999-12-31 00:00:00'
WHERE mv.sys_end_ts = '9999-12-31 00:00:00'
  AND GREATEST(mv.biz_effective_from, cw.biz_effective_from)
      <= LEAST(mv.biz_effective_to, cw.biz_effective_to);

-- -----------------------------------------------------------------------------
-- Current Hierarchies — only active hierarchy records
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ref_data_semla.v_hierarchies AS
SELECT
    h.system_code,
    h.hierarchy_code,
    h.name,
    h.description,
    h.levels,
    h.biz_effective_from,
    h.biz_effective_to,
    h.sys_start_ts
FROM ref_data_core.hierarchy h
WHERE h.sys_end_ts = '9999-12-31 00:00:00';

-- -----------------------------------------------------------------------------
-- Current Hierarchy Values — with container cut-off applied
--
-- Business dates of hierarchy nodes are trimmed by their parent hierarchy's range.
-- Each child has exactly one parent at any given time within the trimmed range.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ref_data_semla.v_hierarchy_values AS
SELECT
    hv.system_code,
    hv.hierarchy_code,
    hv.node_code,
    hv.label,
    hv.level,
    hv.parent_code,
    -- Trimmed business dates
    GREATEST(hv.biz_effective_from, h.biz_effective_from) AS biz_effective_from,
    LEAST(hv.biz_effective_to, h.biz_effective_to)       AS biz_effective_to,
    hv.biz_effective_from AS raw_biz_effective_from,
    hv.biz_effective_to   AS raw_biz_effective_to,
    hv.sys_start_ts
FROM ref_data_core.hierarchy_value hv
JOIN ref_data_core.hierarchy h
    ON hv.system_code = h.system_code
    AND hv.hierarchy_code = h.hierarchy_code
    AND h.sys_end_ts = '9999-12-31 00:00:00'
WHERE hv.sys_end_ts = '9999-12-31 00:00:00'
  AND GREATEST(hv.biz_effective_from, h.biz_effective_from)
      <= LEAST(hv.biz_effective_to, h.biz_effective_to);

-- -----------------------------------------------------------------------------
-- Point-in-Time Helper: Code Values as of a specific date
--
-- Usage:  SELECT * FROM ref_data_semla.v_codevalues
--         WHERE '2023-06-15' BETWEEN biz_effective_from AND biz_effective_to;
-- -----------------------------------------------------------------------------

-- -----------------------------------------------------------------------------
-- Crosswalk Lookup Helper: Translate a source code to target code
--
-- Usage (one-to-one/many-to-one):
--   SELECT target_code FROM ref_data_semla.v_mapping_values
--   WHERE crosswalk_code = 'billing_status_to_crm_status'
--     AND source_code = 'ACTIVE'
--     AND CURRENT_DATE BETWEEN biz_effective_from AND biz_effective_to;
--
-- Usage (one-to-many with routing):
--   SELECT target_code FROM ref_data_semla.v_mapping_values
--   WHERE crosswalk_code = 'app_event_to_activity_category'
--     AND source_code = 'login'
--     AND (routing_condition = 'source_system = ''app_events''' OR is_default = TRUE)
--     AND CURRENT_DATE BETWEEN biz_effective_from AND biz_effective_to
--   ORDER BY is_default ASC  -- prefer specific match over default
--   LIMIT 1;
-- -----------------------------------------------------------------------------
