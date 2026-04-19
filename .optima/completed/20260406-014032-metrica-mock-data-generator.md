# Task: Mock Data Generator for Metrica Pilot Metrics

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-06
**Priority**: High — needed to exercise the DQ pipeline end-to-end
**Depends on**: metrica-project-kickoff (completed ✅)

---

## Goal

Create a realistic mock data generator for the three pilot metrics (`tenure_months`,
`monthly_charges`, `support_calls_30d`) that populates both the **source system tables**
and the **target `metrics.customer_metrics` table** in DuckDB, so we can run the full
DQ pipeline against real data.

---

## Context

The Metrica project has been bootstrapped with:
- Pydantic models in `metrica/registry/models.py` and `metrica/dq/models.py`
- YAML definitions for 3 pilot metrics in `definitions/metrics/`
- SQL schemas in `sql/001_core_schema.sql` (metrics schema) and `sql/002_dq_schema.sql` (DQ schema)
- A `DQStore` in `metrica/dq/store.py` backed by DuckDB
- 6 passing tests in `tests/`

The project is installed as an editable package via `.venv`.

**What's missing**: actual data to run against. The DQ rules reference source tables
(`crm_customers`, `billing_invoices`, `contact_center_interactions`) and a target table
(`metrics.customer_metrics`), but nothing populates them yet.

---

## What to Build

### 1. Mock Data Generator Script — `scripts/generate_mock_data.py`

A standalone Python script (using only packages already in `.venv`: DuckDB, Pydantic, PyYAML)
that creates and populates a DuckDB database file at `data/metrica_mock.duckdb` with:

#### Source Tables (simulating raw source systems)

**`raw.crm_customers`** — 1,000 customers
| Column | Type | Rules |
|--------|------|-------|
| `customer_id` | VARCHAR | `CUST-0001` to `CUST-1000` |
| `activation_date` | DATE | Random date between 2015-01-01 and 2024-12-01 |
| `account_status` | VARCHAR | 90% `active`, 5% `suspended`, 5% `terminated` |
| `contract_type` | VARCHAR | 40% `month_to_month`, 35% `one_year`, 25% `two_year` |
| `reactivation_date` | DATE | NULL for 95%, random date > activation_date for 5% |

**`raw.billing_invoices`** — latest invoice per customer (1,000 rows)
| Column | Type | Rules |
|--------|------|-------|
| `invoice_id` | VARCHAR | Unique `INV-XXXXXX` |
| `customer_id` | VARCHAR | References `crm_customers` |
| `invoice_date` | DATE | Between 2026-02-01 and 2026-03-31 |
| `monthly_charge_amount` | DOUBLE | Normal distribution: mean=65, std=25, min=15, max=300 |
| `base_plan_charge` | DOUBLE | 80% of monthly_charge_amount |
| `add_on_charges` | DOUBLE | remainder |

**`raw.contact_center_interactions`** — variable rows per customer
| Column | Type | Rules |
|--------|------|-------|
| `interaction_id` | VARCHAR | Unique `INT-XXXXXXX` |
| `customer_id` | VARCHAR | References `crm_customers` |
| `interaction_date` | DATE | Last 60 days |
| `interaction_type` | VARCHAR | 70% `call`, 20% `chat`, 10% `email` |
| `channel` | VARCHAR | Same as interaction_type |
| `resolution_status` | VARCHAR | 75% `resolved`, 15% `pending`, 10% `escalated` |

Distribution for calls per customer in last 30 days:
- 60% of customers: 0 calls
- 25%: 1–2 calls
- 10%: 3–5 calls
- 5%: 6+ calls (high-friction customers — potential churners)

#### Target Table

**`metrics.customer_metrics`** — computed from source tables (1,000 rows)
| Column | Derivation |
|--------|-----------|
| `customer_id` | From CRM |
| `tenure_months` | `FLOOR(DATEDIFF('month', activation_date, CURRENT_DATE))` |
| `monthly_charges` | Latest `monthly_charge_amount` from billing_invoices |
| `support_calls_30d` | COUNT of calls in last 30 days from contact_center_interactions |
| `last_updated` | `CURRENT_TIMESTAMP` |

#### Intentional Data Quality Issues (important!)

Inject realistic DQ problems so the pipeline has something to catch:

| Issue | How to inject | Affects |
|-------|--------------|---------|
| **5% null tenure** | Set `activation_date` to NULL for 50 customers | Completeness |
| **2% invalid charges** | Set `monthly_charge_amount` to -5.0 for 20 customers | Validity |
| **1% future activation dates** | Set `activation_date` to 2027-01-01 for 10 customers | Accuracy |
| **Stale billing data** | Set `invoice_date` to 60 days ago for 30 customers | Timeliness |
| **Duplicate interactions** | Insert 20 duplicate `interaction_id` rows | Consistency/Accuracy |

These should be clearly flagged in the script with comments like `# DQ ISSUE: inject nulls`.

---

### 2. DQ Runner Script — `scripts/run_dq_checks.py`

A script that:
1. Connects to `data/metrica_mock.duckdb`
2. Loads all DQ rules from `definitions/metrics/*.yaml` using `DefinitionLoader`
3. Executes each DQ rule's `check_expression` against the actual data
4. Computes dimension scores (pass rate = 1 - failed_rows / total_rows)
5. Records results into `dq.dq_runs` and `dq.dq_scores` via `DQStore`
6. Prints a DQ scorecard to stdout:

```
╔══════════════════════════════════════════════════════╗
║           METRICA DQ SCORECARD                       ║
╠══════════════════════════════════════════════════════╣
║ Metric               │ Dim        │ Score  │ Status  ║
╠══════════════════════════════════════════════════════╣
║ tenure_months        │ completeness│ 0.950 │ ✅ PASS ║
║ tenure_months        │ validity    │ 0.990 │ ✅ PASS ║
║ monthly_charges      │ completeness│ 1.000 │ ✅ PASS ║
║ monthly_charges      │ validity    │ 0.980 │ ⚠️ WARN ║
║ support_calls_30d    │ completeness│ 0.999 │ ✅ PASS ║
╚══════════════════════════════════════════════════════╝
```

---

### 3. Tests — `tests/test_mock_data.py`

Add tests that:
- `test_mock_db_schema()` — verify all expected tables exist after generation
- `test_customer_count()` — exactly 1,000 customers in `raw.crm_customers`
- `test_metrics_computed()` — `metrics.customer_metrics` has 1,000 rows, no all-null rows
- `test_dq_issues_present()` — verify injected DQ issues are actually in the data (e.g., NULL activation_dates exist, negative charges exist)
- `test_dq_runner_produces_scores()` — run `run_dq_checks.py` as a subprocess or import its main function, verify `dq.dq_scores` has rows after execution

---

### 4. Fix Minor Issue from Code Review

While you're in the codebase, please fix this small issue noted in the code review:

In `metrica/registry/loader.py`, the `load_metric_dq_rules()` function returns raw dicts.
Update it to hydrate them into typed `DQRule` objects from `metrica/dq/models.py`.
You'll need to add `target_type` and `target_id` fields (infer from metric_id and `'metric'`),
and `name` (can default to `rule_id` if not present in YAML).

Also fix the `datetime.utcnow()` deprecation warnings in `tests/test_dq_store.py` —
replace with `datetime.now(datetime.UTC)`.

---

## Acceptance Criteria

- [ ] `scripts/generate_mock_data.py` runs cleanly: `python3 scripts/generate_mock_data.py`
- [ ] `data/metrica_mock.duckdb` is created with all source + target tables populated
- [ ] All 5 intentional DQ issues are injected and clearly commented in the script
- [ ] `scripts/run_dq_checks.py` runs cleanly and prints a scorecard
- [ ] DQ scores are persisted in the DuckDB DQ tables
- [ ] New tests in `tests/test_mock_data.py` all pass
- [ ] All previously passing tests still pass (no regressions)
- [ ] `datetime.utcnow()` deprecation warnings are resolved
- [ ] DQ rules loader returns typed `DQRule` objects

## Technical Notes

- Use only packages already in `.venv` (duckdb, pydantic, pyyaml, pytest)
- The DuckDB file should live in `data/` (create the directory if needed, add `data/*.duckdb` to `.gitignore`)
- Use a fixed random seed (`random.seed(42)`) for reproducibility
- The `data/metrica_mock.duckdb` should be re-creatable from scratch by re-running the generator
- Run all tests at the end and report results



---
## Agent Response (2026-04-06 01:40:32)
**Outcome**: completed

Mock data generator and DQ runner complete: 1K customer dataset with 5 injected DQ issues, DQ scorecard runner with 11 executable checks across 3 metrics, 8 new tests (14 total, all passing). Fixed DQ loader to return typed DQRule objects, resolved datetime.utcnow deprecation.
