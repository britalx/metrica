# Task: Metrica Project Kickoff — Metric Management System & Semantic Layer for Telecom

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-01
**Priority**: High — foundational architecture task

---

## Goal

Design and bootstrap the **Metrica** project: a comprehensive **metric management system and semantic layer for telecom**, covering the full end-to-end lifecycle of metrics — from raw source data to curated, quality-assured, monitored business metrics ready for analytics and machine learning.

---

## Project Context & Background

This project emerged from a brainstorming session on **telecom customer churn prediction**. During that session, we identified ~40 features spanning:

- Usage behavior (calls, data, SMS, roaming trends)
- Billing & financials (monthly charges, overages, discount cliffs)
- Contract & account structure (tenure, contract type, device financing)
- Customer service friction (support calls, unresolved tickets, NPS)
- Network & service quality (signal strength, dropped calls, outages)
- Behavioral engagement signals (app logins, recency, referrals)
- Derived/engineered composites (usage decay score, stickiness index, etc.)

The realization was clear: **before any model can trust these features, the underlying metrics need to be governed, tracked, and quality-assured end-to-end**. That is Metrica's purpose.

---

## What Metrica Needs to Cover

### 1. Metric Definitions & Semantic Layer
- Canonical metric registry: each metric has a unique ID, business name, description, owner, domain, and refresh cadence
- Source-to-target mapping: for every metric, document which source system(s) feed it (CRM, CDR, Billing, Network, Contact Center), the transformation logic, and the target table/column in the DWH
- Metric lineage: upstream dependencies, downstream consumers (dashboards, ML features, reports)
- Versioned definitions — metrics can evolve; history must be preserved

### 2. Critical Data Elements (CDEs)
- For each metric, identify the underlying CDEs it depends on
- Each CDE tagged with: source system, business owner, sensitivity classification, update frequency
- CDE-to-metric dependency mapping (many-to-many)

### 3. Data Quality Framework (5 Dimensions)
For every metric and its CDEs, track and automate assessment across:
- **Completeness** — no missing values where mandatory
- **Accuracy** — values reflect real-world truth (range checks, cross-system reconciliation)
- **Consistency** — agreement across systems and time periods
- **Timeliness** — data freshness relative to required SLA
- **Validity** — format, type, business rule conformance

Each dimension scored 0.0–1.0 per metric per run. Composite DQ score with configurable pass/warn/fail thresholds.

### 4. Monitoring & Alerting
- Automated DQ pipeline: scheduled checks, results stored in a DQ metadata store
- Alerting on threshold breaches (Slack / log / file-based notification)
- Trend tracking: detect gradual degradation, not just acute failures
- Feature store gate: block metrics with DQ score below threshold from being served to ML pipelines

### 5. ML Feature Engineering Bridge
- Metrics in Metrica serve as the authoritative source for ML features
- Each ML feature (e.g., support_calls_30d, usage_trend_3m) traces back to one or more Metrica metrics
- The first ML use case is **Customer Churn Prediction**:
  - Target variable: voluntary churn within 30/60/90 days
  - Feature set: ~40 features identified in the brainstorm (see Appendix below)
  - DQ gates apply before features enter any training or inference pipeline

---

## Acceptance Criteria for This Kickoff Task

- [ ] Project structure scaffolded: directory layout for Metrica repo established with clear separation of concerns (definitions, mappings, dq, monitoring, ml-bridge)
- [ ] Metric registry schema designed: data model for metric definitions, CDEs, and source-to-target mappings
- [ ] DQ framework schema designed: how DQ scores are stored, queried, and trended over time
- [ ] 3 pilot metrics fully documented using the framework:
  1. tenure_months — from CRM activation_date
  2. monthly_charges — from Billing system
  3. support_calls_30d — from Contact Center / CRM
- [ ] README.md written at project root explaining Metrica's purpose, architecture, and how to onboard a new metric
- [ ] Technology recommendations: propose the right stack (dbt? Great Expectations? Soda Core? Custom Python? DuckDB? Postgres?) with rationale — keep in mind this is running on **Termux ARM** (Android), so lightweight/embeddable solutions are preferred over heavy JVM-based tools

---

## Technical Constraints

- **Runtime environment**: Termux on Android ARM — no Docker, no JVM, prefer Python-native or SQLite/DuckDB-based solutions
- **Language**: Python primary, SQL secondary
- **Storage**: SQLite or DuckDB preferred for embedded use; file-based YAML/JSON for definitions
- **No external SaaS dependencies** for the core framework — it must be self-contained

---

## Appendix: Churn Feature Inventory (Reference)

The following features were identified as high-value for churn prediction. Metrica should eventually cover all of them:

**Usage Behavior**: avg_monthly_minutes, calls_per_day, data_usage_gb, sms_count, roaming_usage, night_weekend_usage_ratio, usage_trend_3m, feature_adoption_count

**Billing & Financial**: monthly_charges, total_charges_to_date, avg_overage_charges, payment_delays_count, auto_pay_enrolled, last_bill_change_pct, discount_applied, discount_expiry_days

**Contract & Account**: contract_type, tenure_months, months_to_contract_end, num_lines, device_financing_active, device_age_months, plan_tier, num_plan_changes

**Customer Service**: support_calls_30d, support_calls_trend, unresolved_tickets_count, avg_ticket_resolution_days, nps_score, csat_last_interaction, escalation_count, ivr_abandonment_rate

**Network & Quality**: avg_signal_strength_home, dropped_call_rate, outage_events_experienced, data_throttling_events, coverage_complaint_flag, speed_test_avg_mbps

**Behavioral Engagement**: login_app_frequency, days_since_last_login, paperless_billing, referral_made, usage_vs_plan_utilization, competitor_inquiry_flag

**Derived / Engineered**: usage_decay_score, service_distress_index, stickiness_score, value_to_cost_ratio, churn_season_flag, cohort_churn_rate

---

## Notes

- This is the **first task** — foundational. Everything else in Metrica builds on the decisions made here.
- Prefer **extensibility over completeness** in the initial design — better a clean schema that can grow than a monolithic one that is hard to change.
- The system will eventually need to support near-real-time DQ checks (4h SLA for contact center data), so keep that in mind even if the initial implementation is batch.
- Document design decisions and trade-offs in the README or a separate DECISIONS.md.


---
## Agent Response (2026-04-06 01:22:48)
**Outcome**: completed

Metrica project kickoff complete: Pydantic models for metrics/CDEs/sources/DQ, 3 pilot metrics (tenure_months, monthly_charges, support_calls_30d), DuckDB-backed DQ store, YAML definition loader, SQL DDL, 6 passing tests, README with onboarding guide, DECISIONS.md with 7 architecture decisions. Stack: Python+Pydantic+DuckDB+YAML.
