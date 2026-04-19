# Task: Architecture Diagram — End-to-End Metrica Data Flow (Mermaid)

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-06
**Type**: Documentation
**Priority**: Medium — helps Alex and all future contributors understand the full system
**Effort**: Documentation only — no code changes, no test changes

---

## Goal

Create a comprehensive `ARCHITECTURE.md` file at the project root that documents
the full end-to-end data flow of Metrica using **Mermaid diagrams**.

Alex needs to clearly understand: how data moves from raw source files through
every layer of the system, which scripts trigger which transformations, what lives
in each folder, and how everything connects to produce the final churn model output.

---

## What to Produce

### File: `ARCHITECTURE.md` at project root

Structure it with **four diagrams** and supporting prose:

---

### Diagram 1 — High-Level System Overview (flowchart TD)

The big picture: five layers from raw data to model output.

```
Raw Source Data
  [raw.crm_customers, raw.billing_invoices, raw.contact_center_interactions]
       ↓  scripts/generate_mock_data.py
       ↓  (in production: real ETL from CRM / Billing / CDR / Network / App)

Metric Registry (definitions/)
  [51 metric YAMLs, 35 CDEs, 6 source YAMLs]
  → describes WHAT each metric is, WHERE it comes from, HOW to compute it

ETL Pipeline (scripts/run_pipeline.py → metrica/pipeline/)
  [PipelineRunner → MetricTransformer]
  → reads transformation SQL from metric YAMLs
  → writes to metrics.customer_metrics

Data Quality Engine (scripts/run_dq_checks.py → metrica/dq/)
  [DQStore → dq.dq_runs, dq.dq_scores]
  → 11 executable checks across 3 metrics
  → scores 0.0–1.0 per dimension

Monitoring & Alerting (scripts/run_scheduler.py → metrica/monitoring/)
  [DQScheduler → .alerts/]
  → cron/daemon modes, markdown alert files

Feature Store (scripts/run_feature_store.py → metrica/ml_bridge/)
  [FeatureStore → DQ gate → feature matrix]
  → blocks features below 0.90 composite DQ score

ML Model (scripts/run_churn_model.py → metrica/ml/)
  [ChurnDataset → ChurnModelTrainer → ml.model_runs]
  → logistic regression baseline, AUC-ROC evaluation
```

Use this Mermaid flowchart style:

```mermaid
flowchart TD
    subgraph RAW["🗄️ Raw Data Layer (DuckDB: raw.*)"]
        R1[raw.crm_customers\n1000 customers]
        R2[raw.billing_invoices\n1000 invoices]
        R3[raw.contact_center_interactions\n~1555 events]
    end

    subgraph REG["📋 Metric Registry (definitions/)"]
        D1[51 metric YAMLs\ndomain / owner / SQL]
        D2[35 CDE definitions\nsource / sensitivity]
        D3[6 source YAMLs\nCRM / Billing / CDR\nNetwork / CC / App]
    end

    ... and so on for each layer
```

Make it visually clear, use subgraphs for each layer, use emojis on subgraph labels
for quick visual identification.

---

### Diagram 2 — Detailed Data Flow (flowchart LR, left to right)

Show the step-by-step operational flow — what you actually RUN and in what order:

```
Step 1: generate_mock_data.py
  → creates raw.* tables with 5 injected DQ issues
  → seeds metrics.customer_metrics with initial values
  → creates dq.* and pipeline.* table structures

Step 2: run_pipeline.py
  → DefinitionLoader reads all 51 metric YAMLs
  → MetricTransformer executes transformation_sql per metric
  → Upserts results → metrics.customer_metrics
  → Persists run summary → pipeline.pipeline_runs

Step 3: run_dq_checks.py
  → Loads DQ rules from metric YAMLs
  → Executes 11 SQL checks against metrics.* and raw.*
  → Scores 0.0–1.0 per dimension
  → Persists → dq.dq_runs + dq.dq_scores

Step 4: run_scheduler.py --once  [optional, wraps steps 2+3]
  → DQScheduler.run_once()
  → Optionally runs pipeline first (run_before_dq: false by default)
  → Writes .alerts/YYYYMMDD_HHMMSS_<status>.md on WARN/FAIL
  → Updates .alerts/latest.md

Step 5: run_feature_store.py --export-csv
  → FeatureStore queries latest dq.dq_scores per metric
  → Gates metrics below ml_gate=0.90
  → Assembles feature matrix from metrics.customer_metrics
  → Exports → data/churn_features.csv

Step 6: run_churn_model.py --train
  → ChurnDataset builds X (features) and y (churn_label_30d)
  → NULL imputation (column median)
  → StandardScaler + stratified train/test split
  → LogisticRegression(class_weight='balanced')
  → Evaluates: AUC-ROC, precision, recall, F1, confusion matrix
  → Ranks feature importances by |coefficient|
  → Persists → ml.model_runs
```

---

### Diagram 3 — DuckDB Schema Map (erDiagram or flowchart)

Show all 5 schemas and their key tables, with relationships:

```
Schemas:
  raw.*
    crm_customers (customer_id PK, activation_date, account_status,
                   contract_type, reactivation_date, churn_label_30d)
    billing_invoices (invoice_id PK, customer_id FK, invoice_date,
                      monthly_charge_amount, base_plan_charge, add_on_charges)
    contact_center_interactions (interaction_id, customer_id FK,
                                 interaction_date, interaction_type,
                                 channel, resolution_status)

  metrics.*
    customer_metrics (customer_id PK, tenure_months, monthly_charges,
                      support_calls_30d, churn_label_30d, last_updated)
    metric_catalog / cde_catalog / metric_cde_map

  dq.*
    dq_runs (run_id PK, started_at, finished_at, status)
    dq_scores (id PK, run_id FK, target_id, dimension, score, severity)

  pipeline.*
    pipeline_runs (run_id PK, started_at, metrics_succeeded,
                   metrics_failed, total_rows_written, details_json)

  ml.*
    model_runs (run_id PK, model_type, trained_at, auc_roc,
                features_used_json, importances_json, evaluation_json)
```

Use an `erDiagram` or a clean `flowchart` — whichever renders most clearly.

---

### Diagram 4 — Package Dependency Map (flowchart TD)

Show how the Python packages depend on each other:

```
scripts/run_churn_model.py
  → metrica/ml/ (ChurnDataset, ChurnModelTrainer)
    → metrica/ml_bridge/ (FeatureStore)
      → metrica/registry/ (DefinitionLoader, MetricDefinition)
      → metrica/dq/ (DQStore, DQConfig)
    → DuckDB (data/metrica_mock.duckdb)

scripts/run_scheduler.py
  → metrica/monitoring/ (DQScheduler, alerting)
    → scripts/run_dq_checks.py (run_dq_checks function)
    → scripts/run_pipeline.py (PipelineRunner) [optional]

scripts/run_pipeline.py
  → metrica/pipeline/ (PipelineRunner, MetricTransformer)
    → metrica/registry/ (DefinitionLoader)
    → DuckDB

All packages → metrica/dq/models.py (shared DQ types)
All packages → metrica/registry/models.py (shared metric types)
```

---

## Prose Sections to Include

Between the diagrams, add these short prose sections:

### "The Metrica Philosophy" (3-4 sentences)
Explain WHY the system is structured this way — metrics as first-class citizens,
DQ as a gate not an afterthought, the feature store as the ML contract.

### "Run Order" (numbered list)
The exact sequence of commands to go from zero to a trained churn model:
```bash
1. python3 scripts/generate_mock_data.py     # seed raw data
2. python3 scripts/run_pipeline.py           # compute metrics
3. python3 scripts/run_dq_checks.py          # score data quality
4. python3 scripts/run_feature_store.py --export-csv data/churn_features.csv
5. python3 scripts/run_churn_model.py --train
```

### "Key Design Decisions" (bullet list)
- Why DuckDB (not Postgres): embedded, no server, ARM-compatible, fast analytical SQL
- Why YAML definitions (not a database): human-readable, git-diffable, versionable
- Why DQ gate before ML: silent data quality issues corrupt models invisibly
- Why logistic regression first (not XGBoost): interpretable coefficients give DQ feedback
- Why `class_weight='balanced'`: 5% churn rate makes unweighted models useless

### "Current Status" (table)
Show what's real vs placeholder in the current mock data:

| Layer | Status | Notes |
|-------|--------|-------|
| CRM metrics (3) | ✅ Real | tenure_months, monthly_charges, support_calls_30d fully computed |
| CDR metrics (8) | 🔲 Placeholder | No raw CDR table in mock data — NULL values |
| Network metrics (6) | 🔲 Placeholder | No network data — NULL values |
| App metrics (6) | 🔲 Placeholder | No app event data — NULL values |
| Churn model | ✅ Running | 3 features, AUC-ROC ~0.5 (improves with real CDR data) |

---

## Acceptance Criteria

- [ ] `ARCHITECTURE.md` created at project root
- [ ] All 4 Mermaid diagrams present and syntactically valid
- [ ] Diagram 1: high-level 6-layer overview (TD flowchart)
- [ ] Diagram 2: step-by-step operational flow with all 6 scripts
- [ ] Diagram 3: DuckDB schema map with all 5 schemas and key columns
- [ ] Diagram 4: Python package dependency map
- [ ] "The Metrica Philosophy" prose section
- [ ] "Run Order" with exact commands
- [ ] "Key Design Decisions" with rationale
- [ ] "Current Status" table showing real vs placeholder
- [ ] No Python code changes
- [ ] No test changes — all 55 existing tests still pass
- [ ] README.md updated to reference ARCHITECTURE.md

## Technical Notes

- Read the following before writing to get all details right:
  - `README.md` — existing docs
  - `DECISIONS.md` — existing design decisions  
  - `dq_schedule.yaml` — schedule config structure
  - `metrica/dq/models.py` — DQ types
  - `metrica/ml/models.py` — ML types
  - `metrica/ml_bridge/models.py` — feature store types
  - `sql/001_core_schema.sql` through `sql/004_ml_schema.sql` — exact table definitions
- The Mermaid diagrams will be rendered in GitHub / any Markdown viewer
- Use `%%` comments inside Mermaid blocks to add section labels for readability
- Prefer `flowchart TD` for top-down flows and `flowchart LR` for left-to-right pipelines
- The erDiagram for the DB schema should show FK relationships explicitly
- Keep each diagram focused — don't try to show everything in one diagram


---
## Agent Response (2026-04-06 03:37:36)
**Outcome**: completed

ARCHITECTURE.md with 4 Mermaid diagrams (system overview, operational flow, DB schema map, package dependencies), design decisions, run order, current status table. README updated to reference it. 55 tests passing, no code changes.
