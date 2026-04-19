-- Metrica: Core DWH schema for metric storage
-- Target: DuckDB (also compatible with PostgreSQL)

-- Customer metrics: denormalized table holding computed metric values per customer
CREATE TABLE IF NOT EXISTS metrics.customer_metrics (
    customer_id       VARCHAR PRIMARY KEY,
    tenure_months     INTEGER,
    monthly_charges   DOUBLE,
    support_calls_30d INTEGER,
    last_updated      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Metric registry: runtime catalog of all registered metrics
CREATE TABLE IF NOT EXISTS metrics.metric_catalog (
    metric_id       VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    description     VARCHAR,
    domain          VARCHAR NOT NULL,
    owner           VARCHAR,
    refresh_cadence VARCHAR NOT NULL,
    data_type       VARCHAR NOT NULL,
    unit            VARCHAR,
    version         INTEGER DEFAULT 1,
    status          VARCHAR DEFAULT 'active',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- CDE catalog: all critical data elements
CREATE TABLE IF NOT EXISTS metrics.cde_catalog (
    cde_id          VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    description     VARCHAR,
    source_system   VARCHAR NOT NULL,
    source_field    VARCHAR NOT NULL,
    data_type       VARCHAR NOT NULL,
    business_owner  VARCHAR,
    sensitivity     VARCHAR DEFAULT 'internal',
    update_frequency VARCHAR DEFAULT 'daily',
    nullable        BOOLEAN DEFAULT FALSE
);

-- Metric-to-CDE dependency mapping
CREATE TABLE IF NOT EXISTS metrics.metric_cde_map (
    metric_id VARCHAR NOT NULL,
    cde_id    VARCHAR NOT NULL,
    PRIMARY KEY (metric_id, cde_id)
);
