# User Story: Payment Default Prediction

## Title
As a **revenue assurance analyst**, I want to predict which customers are likely to miss their next payment, so that I can trigger proactive interventions (payment reminders, flexible payment plans) before the default occurs.

## Background
Late payments directly impact cash flow and increase collection costs. Customers who default on payments are also at elevated churn risk. By predicting payment default 7–14 days before the due date, the business can intervene with targeted outreach.

## Acceptance Criteria

1. **Target Variable**: `late_payment_flag` — binary label (1 = payment received >7 days after due date or not received within 30 days, 0 = on-time)
2. **Feature Sources**:
   - `billing_invoices`: payment_date vs due_date history, overage_amount, monthly_charge trends
   - `crm_customers`: tenure, contract_end_date, paperless_flag, auto-pay status
   - `contact_center_interactions`: recent support calls (billing-related), CSAT scores
   - `app_events`: view_bill frequency, login recency
3. **Model Requirements**:
   - Train via existing `train_multi()` infrastructure (LR, RF, GB)
   - Disagreement tracking enabled for flagged customers
   - AUC-ROC > 0.75 on test set
   - Feature importances ranked and persisted
4. **Mock Data**:
   - Generate `late_payment_flag` in mock data with ~8-12% default rate
   - Correlate with: low tenure, high overage, infrequent app logins, month-to-month contracts
   - Include ~10% "imperfect" defaulters (long-tenure customers who still default — life events)
5. **Output**:
   - Predictions stored in `ml.model_runs` with `target_variable = 'late_payment_flag'`
   - Per-customer default probability accessible via Feature Store
6. **Tests**:
   - Dataset builds without error
   - Model trains and persists results
   - AUC-ROC above chance (>0.5)
   - Feature importances populated

## Definition of Done
- [ ] Mock data generator produces `late_payment_flag` with realistic correlations
- [ ] YAML metric definition created: `definitions/metrics/late_payment_flag.yaml`
- [ ] `train_multi()` works with `target_variable='late_payment_flag'` parameter
- [ ] Disagreement tracking and champion/challenger governance apply
- [ ] Tests pass (all existing + new)
- [ ] DQ checks cover the new metric

## Priority
**High** — directly monetizable, minimal new infrastructure needed

## Estimated Complexity
**Medium** — reuses existing multi-model pipeline, main work is mock data generation and parameterizing the trainer for multiple target variables


---
## Agent Response (2026-04-19 21:01:55)
**Outcome**: completed

Brainstorming review posted to Discussion #2. Story is well-scoped; flagged temporal leakage risk, target edge cases, feature engineering ideas, and class-imbalance metric suggestions. Implementation belongs to Main.
