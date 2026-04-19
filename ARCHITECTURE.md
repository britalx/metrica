# Architecture

End-to-end data flow documentation for the Metrica metric management system.

---

## The Metrica Philosophy

Metrics are first-class citizens — every metric has a YAML definition with owner, domain, lineage, and transformation SQL, all version-controlled in Git. Data quality is a **gate**, not an afterthought: the Feature Store refuses to serve metrics that fail the 0.90 composite DQ threshold, ensuring that ML models never silently train on corrupt data. The Feature Store acts as the **ML contract** — data scientists interact with governed, quality-assured feature vectors, never raw tables.

---

## Diagram 1 — High-Level System Overview

```mermaid
flowchart TD
    subgraph RAW["🗄️ Raw Data Layer (DuckDB: raw.*)"]
        R1["raw.crm_customers\n1000 customers"]
        R2["raw.billing_invoices\n1000 invoices"]
        R3["raw.contact_center_interactions\n~1555 events"]
    end

    subgraph REG["📋 Metric Registry (definitions/)"]
        D1["51 metric YAMLs\ndomain · owner · SQL"]
        D2["35 CDE definitions\nsource · sensitivity"]
        D3["6 source YAMLs\nCRM · Billing · CDR\nNetwork · CC · App"]
    end

    subgraph ETL["⚙️ ETL Pipeline (metrica/pipeline/)"]
        P1["PipelineRunner"]
        P2["MetricTransformer"]
        P3["metrics.customer_metrics\n1000 rows × 51 columns"]
    end

    subgraph DQ["🔍 Data Quality Engine (metrica/dq/)"]
        Q1["DQStore"]
        Q2["11 executable checks\n5 dimensions"]
        Q3["dq.dq_runs + dq.dq_scores"]
    end

    subgraph MON["📢 Monitoring & Alerting (metrica/monitoring/)"]
        M1["DQScheduler\ncron · daemon"]
        M2[".alerts/*.md"]
    end

    subgraph FS["🔒 Feature Store (metrica/ml_bridge/)"]
        F1["FeatureStore"]
        F2["DQ Gate\nthreshold: 0.90"]
        F3["Feature Matrix\npassed · gated · unknown"]
    end

    subgraph ML["🤖 ML Model (metrica/ml/)"]
        L1["ChurnDataset\nNULL imputation · scaling"]
        L2["ChurnModelTrainer\nLogisticRegression"]
        L3["ml.model_runs\nAUC-ROC · importances"]
    end

    RAW --> ETL
    REG --> ETL
    ETL --> DQ
    DQ --> MON
    DQ --> FS
    ETL --> FS
    FS --> ML
```

---

## Diagram 2 — Operational Flow (Run Order)

```mermaid
flowchart LR
    S1["1️⃣ generate_mock_data.py\n\nCreates raw.* tables\nSeeds metrics.*\nInjects 5 DQ issues"]
    S2["2️⃣ run_pipeline.py\n\nReads 51 metric YAMLs\nExecutes transformation SQL\nUpserts → customer_metrics\nPersists → pipeline_runs"]
    S3["3️⃣ run_dq_checks.py\n\n11 SQL checks\nScores 0.0–1.0 per dimension\nPersists → dq_runs + dq_scores"]
    S4["4️⃣ run_scheduler.py\n--once / --daemon\n\nWraps pipeline + DQ\nWrites .alerts/*.md\nUpdates latest.md"]
    S5["5️⃣ run_feature_store.py\n--export-csv\n\nQueries latest DQ scores\nGates metrics < 0.90\nAssembles feature matrix\nExports CSV"]
    S6["6️⃣ run_churn_model.py\n--train\n\nBuilds X, y arrays\nMedian imputation\nStandardScaler + split\nLogisticRegression\nPersists → model_runs"]

    S1 --> S2 --> S3 --> S4
    S3 --> S5 --> S6
```

### Run Order

```bash
# From zero to a trained churn model:
1. python3 scripts/generate_mock_data.py          # seed raw data (1000 customers, 5 DQ issues)
2. python3 scripts/run_pipeline.py                 # compute metrics (raw.* → metrics.customer_metrics)
3. python3 scripts/run_dq_checks.py                # score data quality (11 checks → dq.dq_scores)
4. python3 scripts/run_feature_store.py --gate-status                 # inspect DQ gate
5. python3 scripts/run_feature_store.py --export-csv data/features.csv  # export feature matrix
6. python3 scripts/run_churn_model.py --train      # train baseline churn model
```

---

## Diagram 3 — DuckDB Schema Map

```mermaid
erDiagram
    RAW_CRM_CUSTOMERS {
        VARCHAR customer_id PK
        DATE activation_date
        VARCHAR account_status
        VARCHAR contract_type
        DATE reactivation_date
        INTEGER churn_label_30d
    }

    RAW_BILLING_INVOICES {
        VARCHAR invoice_id PK
        VARCHAR customer_id FK
        DATE invoice_date
        DOUBLE monthly_charge_amount
        DOUBLE base_plan_charge
        DOUBLE add_on_charges
    }

    RAW_CONTACT_CENTER {
        VARCHAR interaction_id
        VARCHAR customer_id FK
        DATE interaction_date
        VARCHAR interaction_type
        VARCHAR channel
        VARCHAR resolution_status
    }

    METRICS_CUSTOMER_METRICS {
        VARCHAR customer_id PK
        INTEGER tenure_months
        DOUBLE monthly_charges
        INTEGER support_calls_30d
        INTEGER churn_label_30d
        TIMESTAMP last_updated
    }

    DQ_RUNS {
        VARCHAR run_id PK
        VARCHAR target_id
        DOUBLE composite_score
        VARCHAR overall_severity
        TIMESTAMP run_started_at
        TIMESTAMP run_finished_at
    }

    DQ_SCORES {
        INTEGER id PK
        VARCHAR run_id FK
        VARCHAR rule_id
        VARCHAR target_id
        VARCHAR dimension
        DOUBLE score
        VARCHAR severity
        INTEGER records_checked
        INTEGER records_failed
        TIMESTAMP checked_at
    }

    PIPELINE_RUNS {
        VARCHAR run_id PK
        TIMESTAMP started_at
        TIMESTAMP finished_at
        DOUBLE duration_seconds
        INTEGER metrics_attempted
        INTEGER metrics_succeeded
        INTEGER metrics_failed
        INTEGER total_rows_written
        VARCHAR status
        VARCHAR details_json
    }

    ML_MODEL_RUNS {
        VARCHAR run_id PK
        VARCHAR model_type
        TIMESTAMP trained_at
        INTEGER training_customers
        INTEGER test_customers
        VARCHAR features_used_json
        VARCHAR features_gated_json
        DOUBLE auc_roc
        DOUBLE accuracy
        DOUBLE dq_gate_threshold
        VARCHAR evaluation_json
        VARCHAR importances_json
    }

    RAW_CRM_CUSTOMERS ||--o{ RAW_BILLING_INVOICES : "customer_id"
    RAW_CRM_CUSTOMERS ||--o{ RAW_CONTACT_CENTER : "customer_id"
    RAW_CRM_CUSTOMERS ||--|| METRICS_CUSTOMER_METRICS : "customer_id"
    DQ_RUNS ||--o{ DQ_SCORES : "run_id"
```

### Schema Summary

| Schema | Tables | Purpose |
|--------|--------|---------|
| `raw.*` | crm_customers, billing_invoices, contact_center_interactions | Source data (mock or real ingestion) |
| `metrics.*` | customer_metrics, metric_catalog, cde_catalog, metric_cde_map | Computed metrics and registry catalog |
| `dq.*` | dq_runs, dq_scores | Data quality run history and per-dimension scores |
| `pipeline.*` | pipeline_runs | ETL run tracking (attempts, successes, failures) |
| `ml.*` | model_runs | Model training history, evaluation metrics, feature importances |

---

## Diagram 4 — Package Dependency Map

```mermaid
flowchart TD
    subgraph SCRIPTS["📜 CLI Scripts"]
        S_MODEL["run_churn_model.py"]
        S_FS["run_feature_store.py"]
        S_DQ["run_dq_checks.py"]
        S_PIPE["run_pipeline.py"]
        S_SCHED["run_scheduler.py"]
        S_MOCK["generate_mock_data.py"]
    end

    subgraph ML["metrica/ml/"]
        ML_TRAINER["ChurnModelTrainer"]
        ML_DATASET["ChurnDataset"]
        ML_MODELS["ModelRunResult\nModelEvaluation\nFeatureImportance"]
    end

    subgraph BRIDGE["metrica/ml_bridge/"]
        FS_STORE["FeatureStore"]
        FS_EXPORT["exporter\nCSV · Parquet · summary"]
        FS_MODELS["FeatureVector\nFeatureMatrix\nGateStatusReport"]
    end

    subgraph REGISTRY["metrica/registry/"]
        REG_LOADER["DefinitionLoader"]
        REG_MODELS["MetricDefinition\nCDE · SourceSystem"]
    end

    subgraph DQ["metrica/dq/"]
        DQ_STORE["DQStore"]
        DQ_MODELS["DQRule · DQScore\nDQConfig · DQDimension"]
    end

    subgraph MONITORING["metrica/monitoring/"]
        MON_SCHED["DQScheduler"]
        MON_ALERT["alerting"]
    end

    subgraph PIPELINE["metrica/pipeline/"]
        PIPE_RUNNER["PipelineRunner"]
        PIPE_TRANS["MetricTransformer"]
    end

    DB[("DuckDB\ndata/metrica_mock.duckdb")]

    S_MODEL --> ML_TRAINER
    ML_TRAINER --> ML_DATASET --> FS_STORE
    ML_TRAINER --> ML_MODELS
    S_FS --> FS_STORE
    S_FS --> FS_EXPORT
    FS_STORE --> REG_LOADER
    FS_STORE --> DQ_MODELS
    S_DQ --> DQ_STORE
    S_DQ --> DQ_MODELS
    S_DQ --> REG_LOADER
    S_PIPE --> PIPE_RUNNER
    PIPE_RUNNER --> PIPE_TRANS
    PIPE_RUNNER --> REG_LOADER
    S_SCHED --> MON_SCHED
    MON_SCHED --> MON_ALERT
    S_MOCK --> DB
    FS_STORE --> DB
    ML_TRAINER --> DB
    DQ_STORE --> DB
    PIPE_RUNNER --> DB
```

---

## Key Design Decisions

- **Why DuckDB (not Postgres)**: Embedded, zero-server, ARM-compatible (Termux), fast columnar analytical SQL. Perfect for append-mostly DQ scoring and metric queries. No Docker, no systemd, no JVM.

- **Why YAML definitions (not a database)**: Human-readable, git-diffable, versionable. Domain experts can review metric definitions in pull requests. The Python loader hydrates YAMLs into Pydantic models at runtime.

- **Why DQ gate before ML**: Silent data quality issues corrupt models invisibly. The Feature Store refuses to serve features below the 0.90 gate threshold, forcing data quality issues to be resolved before they reach the model.

- **Why logistic regression first (not XGBoost)**: Interpretable coefficients give direct feedback on which features matter and which DQ-gated features *would have* contributed — informing DQ prioritization. Baseline first, ensemble later.

- **Why `class_weight='balanced'`**: Mock data has ~5% churn rate. An unweighted model predicts all-0 and achieves 95% accuracy with 0% recall. Balanced weighting forces the model to actually learn the minority class.

- **Why custom DQ framework (not Great Expectations / Soda)**: ~200 lines of Python vs. heavy dependencies with JVM-adjacent ecosystems. DQ rules live alongside metric definitions in YAML. Full control, minimal footprint on ARM.

---

## Current Status

| Layer | Status | Notes |
|-------|--------|-------|
| CRM metrics (3) | ✅ Real | tenure_months, monthly_charges, support_calls_30d — fully computed from raw data |
| Churn label | ✅ Real | churn_label_30d derived from account_status (5% terminated) |
| DQ checks | ✅ Real | 11 checks across 3 metrics, 5 dimensions, persistent scores |
| CDR metrics (8) | 🔲 Placeholder | No raw CDR table in mock data — NULL values in customer_metrics |
| Network metrics (6) | 🔲 Placeholder | No network data — NULL values |
| App metrics (6) | 🔲 Placeholder | No app event data — NULL values |
| Billing extras (7) | 🔲 Placeholder | avg_overage_charges, payment_delays_count, etc. — NULL |
| Derived/Engineered (14) | 🔲 Placeholder | stickiness_score, service_distress_index, etc. — NULL |
| Churn model | ✅ Running | 3 real features + 47 NULL features. AUC improves with real CDR/Network data |
| Feature Store | ✅ Operational | DQ gate blocks 47 metrics with composite score 0.0 (no DQ checks yet) |

### Test Suite

55 tests across 7 test files, all passing:

| File | Tests | Coverage |
|------|-------|----------|
| test_definitions.py | 5 | Registry loading, validation |
| test_dq_store.py | 2 | DQ persistence, trends |
| test_feature_store.py | 12 | Gate logic, feature retrieval, export |
| test_mock_data.py | 8 | Schema, DQ issues, data counts |
| test_pipeline.py | 10 | ETL transformer, runner, idempotency |
| test_scheduler.py | 7 | Scheduler config, alerts, run modes |
| test_churn_model.py | 11 | Dataset, trainer, importances, persistence |
