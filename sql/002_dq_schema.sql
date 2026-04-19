-- Metrica: DQ metadata schema
-- Stores DQ run results and individual dimension scores

CREATE TABLE IF NOT EXISTS dq.dq_runs (
    run_id          VARCHAR PRIMARY KEY,
    target_id       VARCHAR NOT NULL,
    composite_score DOUBLE NOT NULL,
    overall_severity VARCHAR NOT NULL,
    run_started_at  TIMESTAMP NOT NULL,
    run_finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dq.dq_scores (
    id              INTEGER PRIMARY KEY,
    run_id          VARCHAR NOT NULL,
    rule_id         VARCHAR NOT NULL,
    target_id       VARCHAR NOT NULL,
    dimension       VARCHAR NOT NULL,
    score           DOUBLE NOT NULL,
    severity        VARCHAR NOT NULL,
    records_checked INTEGER DEFAULT 0,
    records_failed  INTEGER DEFAULT 0,
    details         VARCHAR DEFAULT '',
    checked_at      TIMESTAMP NOT NULL
);

-- Index for trend queries
CREATE INDEX IF NOT EXISTS idx_dq_scores_target
    ON dq.dq_scores(target_id, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_dq_runs_target
    ON dq.dq_runs(target_id, run_started_at DESC);
