-- Metrica: Pipeline metadata schema
-- Stores ETL run history and per-metric results

CREATE SCHEMA IF NOT EXISTS pipeline;

CREATE TABLE IF NOT EXISTS pipeline.pipeline_runs (
    run_id            VARCHAR PRIMARY KEY,
    started_at        TIMESTAMP NOT NULL,
    finished_at       TIMESTAMP NOT NULL,
    duration_seconds  DOUBLE NOT NULL,
    metrics_attempted INTEGER NOT NULL,
    metrics_succeeded INTEGER NOT NULL,
    metrics_failed    INTEGER NOT NULL,
    total_rows_written INTEGER NOT NULL,
    status            VARCHAR NOT NULL,
    details_json      VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started
    ON pipeline.pipeline_runs(started_at DESC);
