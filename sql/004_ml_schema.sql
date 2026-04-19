-- Metrica: ML schema for model run tracking
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.model_runs (
    run_id              VARCHAR PRIMARY KEY,
    model_type          VARCHAR NOT NULL,
    trained_at          TIMESTAMP NOT NULL,
    training_customers  INTEGER NOT NULL,
    test_customers      INTEGER NOT NULL,
    features_used_json  VARCHAR NOT NULL,
    features_gated_json VARCHAR NOT NULL,
    churn_rate_train    DOUBLE NOT NULL,
    churn_rate_test     DOUBLE NOT NULL,
    auc_roc             DOUBLE NOT NULL,
    avg_precision       DOUBLE NOT NULL,
    accuracy            DOUBLE NOT NULL,
    precision_score     DOUBLE NOT NULL,
    recall_score        DOUBLE NOT NULL,
    f1_score            DOUBLE NOT NULL,
    dq_gate_threshold   DOUBLE NOT NULL,
    evaluation_json     VARCHAR NOT NULL,
    importances_json    VARCHAR NOT NULL,
    notes               VARCHAR DEFAULT '',
    run_group_id        VARCHAR,
    is_champion         BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS ml.model_disagreements (
    run_group_id    VARCHAR NOT NULL,
    customer_id     VARCHAR NOT NULL,
    predictions_json VARCHAR NOT NULL,
    max_divergence  DOUBLE NOT NULL,
    flagged         BOOLEAN NOT NULL
);
