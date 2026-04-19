# Task: Story 1.3 — Expand Metric Registry to All 40 Churn Features

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-06
**Epic**: 1 — Registry & Definitions
**Priority**: Medium-High — runs in parallel with Story 4.1 (ETL pipeline)
**Effort estimate**: Pure YAML authoring + 1 test update — no core code changes needed

---

## Context & Where We Are

The registry currently has **3 pilot metrics** fully defined in `definitions/metrics/`:
- `tenure_months.yaml`
- `monthly_charges.yaml`
- `support_calls_30d.yaml`

These 3 metrics proved the pattern works end-to-end. Now we need to expand to the
**full set of ~40 telecom churn features** that Metrica is ultimately designed to serve.

This story is pure definition work — you're authoring YAML files that follow the exact
same pattern as the 3 pilots. Look at the existing YAMLs carefully before starting.
The `definitions/` structure already supports this:

```
definitions/
├── metrics/      ← add 37 new .yaml files here
├── cdes/         ← add new CDEs as needed
└── sources/      ← crm.yaml, billing.yaml, contact_center.yaml already exist
                    add new sources if needed (e.g. network.yaml, app_events.yaml)
```

The goal: **every churn feature has a YAML definition** so Metrica can govern,
quality-check, and serve it to the ML pipeline.

---

## The 40 Churn Features — Full Inventory

Organised by domain. Each becomes one `definitions/metrics/<metric_id>.yaml` file.

### Domain: `usage_behavior`
| metric_id | Description | Source System | Key CDEs |
|---|---|---|---|
| `avg_monthly_minutes` | Average call minutes per month (last 3 months) | CDR | cdr.call_duration, cdr.call_date |
| `calls_per_day` | Average daily call frequency (last 30 days) | CDR | cdr.call_start_time |
| `data_usage_gb` | Monthly data consumption in GB | CDR / Network | cdr.data_bytes_transferred |
| `sms_count` | Monthly SMS volume | CDR | cdr.sms_event |
| `roaming_usage` | Roaming minutes + data used (last 30 days) | CDR | cdr.roaming_flag |
| `night_weekend_usage_ratio` | (Night+Weekend usage) / Total usage | CDR | cdr.call_start_time |
| `usage_trend_3m` | Linear slope of monthly usage over last 3 months (negative = declining) | CDR | cdr.data_bytes_transferred, cdr.call_duration |
| `feature_adoption_count` | Count of distinct services actively used (voicemail, hotspot, etc.) | CRM / Provisioning | crm.provisioned_services |

### Domain: `billing_financial`
| metric_id | Description | Source System | Key CDEs |
|---|---|---|---|
| `total_charges_to_date` | Cumulative lifetime revenue from customer | Billing | billing.invoice_amount |
| `avg_overage_charges` | Average overage fees per month (last 6 months) | Billing | billing.overage_amount |
| `payment_delays_count` | Count of late payments in last 12 months | Billing | billing.payment_date, billing.due_date |
| `auto_pay_enrolled` | Boolean: customer enrolled in autopay | Billing / CRM | crm.autopay_flag |
| `last_bill_change_pct` | % change in most recent bill vs. prior month | Billing | billing.invoice_amount |
| `discount_applied` | Boolean: customer currently on a promotion | Billing / Promo | billing.discount_code |
| `discount_expiry_days` | Days until current promotional discount expires | Billing / Promo | billing.discount_end_date |

*(Note: `monthly_charges` already exists — skip it here)*

### Domain: `contract_account`
| metric_id | Description | Source System | Key CDEs |
|---|---|---|---|
| `months_to_contract_end` | Months remaining until contract expiry | CRM | crm.contract_end_date |
| `num_lines` | Number of active lines on the account | CRM | crm.line_count |
| `device_financing_active` | Boolean: customer on device installment plan | CRM / Billing | crm.device_financing_flag |
| `device_age_months` | Age in months of customer's current primary device | CRM / Device | crm.device_activation_date |
| `plan_tier` | Plan tier encoded as integer: 1=Basic, 2=Mid, 3=Premium | CRM | crm.plan_code |
| `num_plan_changes` | Count of plan up/downgrades in last 12 months | CRM | crm.plan_change_log |
| `contract_type_encoded` | Contract type as integer: 0=MTM, 1=1yr, 2=2yr | CRM | crm.contract_type |

*(Note: `tenure_months` and `contract_type` already exist — map `contract_type_encoded` as a derived variant)*

### Domain: `customer_service`
| metric_id | Description | Source System | Key CDEs |
|---|---|---|---|
| `support_calls_trend` | Slope of support call volume over last 3 months (positive = escalating) | Contact Center | cc.interaction_date |
| `unresolved_tickets_count` | Count of open/unresolved support tickets | CRM / Ticketing | crm.ticket_status |
| `avg_ticket_resolution_days` | Average days to resolve a ticket (last 6 months) | CRM / Ticketing | crm.ticket_created_at, crm.ticket_resolved_at |
| `nps_score` | Net Promoter Score from last survey (-100 to 100) | CRM / Survey | crm.nps_response |
| `csat_last_interaction` | Customer satisfaction score from last contact (1–5) | Contact Center | cc.csat_score |
| `escalation_count` | Count of escalations to supervisor in last 90 days | Contact Center | cc.escalation_flag |
| `ivr_abandonment_rate` | % of IVR calls abandoned before reaching an agent (last 30 days) | Contact Center | cc.ivr_abandon_flag |

*(Note: `support_calls_30d` already exists — skip it)*

### Domain: `network_quality`
| metric_id | Description | Source System | Key CDEs |
|---|---|---|---|
| `avg_signal_strength_home` | Average signal RSRP at customer's home location (dBm) | Network / CDR | network.rsrp, network.cell_id |
| `dropped_call_rate` | % of calls dropped in last 30 days | Network / CDR | cdr.drop_flag |
| `outage_events_experienced` | Count of network outage events in customer's coverage zone (last 90 days) | Network / NOC | network.outage_events |
| `data_throttling_events` | Count of times customer's data was throttled (last 30 days) | Network / Policy | network.throttle_events |
| `coverage_complaint_flag` | Boolean: customer has ever filed a coverage complaint | CRM / Contact Center | crm.complaint_category |
| `speed_test_avg_mbps` | Average data speed from speed tests (if available) | App / Network | app.speed_test_result |

### Domain: `behavioral_engagement`
| metric_id | Description | Source System | Key CDEs |
|---|---|---|---|
| `login_app_frequency` | Average app logins per week (last 30 days) | App Events | app.login_event |
| `days_since_last_login` | Days since last app/portal login | App Events | app.login_event |
| `paperless_billing` | Boolean: enrolled in paperless billing | CRM / Billing | crm.paperless_flag |
| `referral_made` | Boolean: customer has referred at least one person | CRM | crm.referral_flag |
| `usage_vs_plan_utilization` | Actual usage / Plan allowance — ratio 0.0 to 1.0+ | CDR + CRM | cdr.data_bytes_transferred, crm.plan_data_allowance |
| `competitor_inquiry_flag` | Boolean: customer has contacted retention or shown competitor interest | CRM / Contact Center | crm.retention_contact_flag |

### Domain: `derived_engineered`
| metric_id | Description | Derivation |
|---|---|---|
| `usage_decay_score` | Weighted slope of usage trend over 3m and 6m windows — higher = more decay | Derived from CDR via SQL |
| `service_distress_index` | Composite: normalised(support_calls_30d) + normalised(unresolved_tickets) + normalised(1-nps_score/100) | Derived from other metrics |
| `stickiness_score` | num_lines × (1 + device_financing_active) × months_to_contract_end | Derived from contract metrics |
| `value_to_cost_ratio` | feature_adoption_count / monthly_charges | Derived |
| `churn_season_flag` | Boolean: current month is historically high-churn (Jan, Sep) | Derived from calendar |
| `cohort_churn_rate` | Historical churn rate of customers with same tenure_band + plan_tier | Derived from historical data |

---

## How to Write Each YAML

Follow the exact structure of the existing pilots. Read `definitions/metrics/tenure_months.yaml`
and `definitions/metrics/support_calls_30d.yaml` before writing anything.

The key fields every metric YAML must have:

```yaml
metric_id: avg_monthly_minutes
name: "Average Monthly Call Minutes"
description: >
  Average call minutes per month over the last 3 months.
  Used as a primary usage engagement signal for churn prediction.
domain: usage_behavior
owner: "data-engineering"
refresh_cadence: daily
data_type: float
unit: minutes

source_mappings:
  - source_id: cdr
    source_table: cdr.call_records
    transformation_sql: |
      SELECT customer_id,
             AVG(monthly_minutes) AS avg_monthly_minutes
      FROM (
          SELECT customer_id,
                 DATE_TRUNC('month', call_date) AS month,
                 SUM(duration_seconds) / 60.0 AS monthly_minutes
          FROM raw.cdr_call_records
          WHERE call_date >= CURRENT_DATE - INTERVAL '90 days'
          GROUP BY customer_id, DATE_TRUNC('month', call_date)
      ) monthly
      GROUP BY customer_id

lineage:
  upstream_cdes:
    - cdr.call_duration
    - cdr.call_date
  downstream_consumers:
    - ml.churn_features
    - dashboard.usage_summary

dq_rules:
  - rule_id: avg_monthly_minutes_completeness
    name: "All active customers have a minutes value"
    dimension: completeness
    check_expression: |
      SELECT 1.0 - (COUNT(*) FILTER (WHERE avg_monthly_minutes IS NULL)::FLOAT / COUNT(*))
      FROM metrics.customer_metrics
    warn_threshold: 0.95
    fail_threshold: 0.80

  - rule_id: avg_monthly_minutes_validity
    name: "Minutes value is non-negative and within plausible range"
    dimension: validity
    check_expression: |
      SELECT 1.0 - (COUNT(*) FILTER (WHERE avg_monthly_minutes < 0 OR avg_monthly_minutes > 10000)::FLOAT / NULLIF(COUNT(*),0))
      FROM metrics.customer_metrics
    warn_threshold: 0.99
    fail_threshold: 0.95

tags:
  - churn_feature
  - usage_behavior
  - ml_ready

version: "1.0"
status: active
```

**Rules for writing the transformation SQL:**
- Always alias the computed column as the `metric_id` exactly
- Read from `raw.*` tables (the source schema in the mock DB)
- For metrics that don't have a real source table yet (e.g. network metrics, app events),
  write a **placeholder SQL** that selects NULL with a comment explaining what the real
  source would be:

```sql
-- PLACEHOLDER: network.rsrp not available in mock data
-- Real source: SELECT customer_id, AVG(rsrp_dbm) AS avg_signal_strength_home
--              FROM raw.network_measurements WHERE ...
SELECT customer_id, NULL::FLOAT AS avg_signal_strength_home
FROM raw.crm_customers
```

**For derived/engineered metrics** — write the derivation SQL using already-computed
values in `metrics.customer_metrics` rather than raw tables:

```sql
-- Derived from metrics layer (not raw sources)
SELECT customer_id,
       feature_adoption_count / NULLIF(monthly_charges, 0) AS value_to_cost_ratio
FROM metrics.customer_metrics
```

---

## New Source Definitions Needed

Add these to `definitions/sources/` if they don't exist:

```
definitions/sources/
├── crm.yaml           ✅ exists
├── billing.yaml       ✅ exists
├── contact_center.yaml ✅ exists
├── cdr.yaml           🔲 new — Call Detail Records
├── network.yaml       🔲 new — Network measurements / NOC
└── app_events.yaml    🔲 new — Mobile app event stream
```

Each follows the same pattern as the existing source YAMLs.

---

## New CDEs Needed

For each new source, add representative CDEs to `definitions/cdes/`. You don't need to
add every possible CDE — just the ones actually referenced in `upstream_cdes` of the
metric YAMLs you're writing. Aim for coverage without exhaustiveness.

Key new CDEs to define:
- `cdr.call_duration`
- `cdr.call_date`
- `cdr.data_bytes_transferred`
- `cdr.roaming_flag`
- `network.rsrp`
- `network.outage_events`
- `app.login_event`
- `crm.contract_end_date`
- `crm.device_financing_flag`
- `crm.nps_response`
- `crm.retention_contact_flag`
- `billing.discount_end_date`
- `billing.overage_amount`

---

## What NOT to Change

- **No Python code changes** — this is pure YAML authoring
- **No changes to existing metric YAMLs** — the 3 pilots are correct, leave them alone
- **No database changes** — `metrics.customer_metrics` will grow columns in a future story; for now just write the YAMLs
- **No test changes for existing tests** — they must still pass

---

## Acceptance Criteria

- [ ] All 37 new metric YAMLs written (the 40 minus the 3 that already exist)
- [ ] Each YAML follows the exact schema of the pilot metrics (metric_id, name, description, domain, owner, refresh_cadence, data_type, unit, source_mappings, lineage, dq_rules, tags, version, status)
- [ ] Every metric has at least 2 DQ rules (completeness + validity minimum)
- [ ] Derived metrics use `metrics.customer_metrics` as source, not `raw.*`
- [ ] Placeholder SQL used for metrics where raw source tables don't exist in mock DB
- [ ] 3 new source YAMLs: `cdr.yaml`, `network.yaml`, `app_events.yaml`
- [ ] New CDEs added for all referenced upstream fields
- [ ] `DefinitionLoader` can load all metrics without error (`loader.metrics()` returns 40 metrics)
- [ ] Existing 21 tests still pass — zero regressions
- [ ] Add 1 new test: `test_all_40_metrics_load()` — asserts `len(loader.metrics()) == 40`
- [ ] Run `pytest tests/ -v` at the end and confirm

## Technical Notes

- The `DefinitionLoader` reads all `.yaml` files in `definitions/metrics/` — adding files there is all that's needed
- Check `refresh_cadence` values are from the allowed enum: `hourly`, `daily`, `weekly`, `monthly`
- Check `data_type` values are from the allowed enum: `integer`, `float`, `boolean`, `string`, `timestamp`
- Boolean metrics (`auto_pay_enrolled`, `paperless_billing`, etc.) use `data_type: boolean` and `unit: flag`
- Integer counts use `data_type: integer`
- Ratios and scores use `data_type: float`
- The `domain` field should be exactly one of: `usage_behavior`, `billing_financial`, `contract_account`, `customer_service`, `network_quality`, `behavioral_engagement`, `derived_engineered`
- Don't overthink the transformation SQL — correctness of structure matters more than SQL perfection for placeholder metrics


---
## Agent Response (2026-04-06 02:40:41)
**Outcome**: completed

Expanded registry to 50 churn feature definitions across 7 domains. Created 47 new metric YAMLs, 3 source YAMLs (cdr, network, app_events), 31 CDE definitions. Each metric includes completeness + validity DQ rules. Placeholder SQL for metrics without mock data. All 32 tests passing.
