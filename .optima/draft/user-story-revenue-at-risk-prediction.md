# User Story: Revenue at Risk (ARPU Decline) Prediction

## Title
As a **revenue management analyst**, I want to predict which customers are likely to experience a significant decline in Average Revenue Per User (ARPU) over the next 30 days, so that I can target them with retention offers, plan upgrades, or engagement campaigns before revenue erodes.

## Background
ARPU decline is a leading indicator of both churn and plan downgrades. Customers who reduce usage or switch to cheaper plans represent revenue leakage that compounds over time. Unlike churn (binary loss), ARPU decline captures the "silent revenue erosion" where customers stay but spend less — often harder to detect but equally damaging.

## Acceptance Criteria

1. **Target Variable**: `arpu_decline_flag` — binary label (1 = customer's monthly charge drops by >15% in the next billing cycle, or overage drops to zero after previous overages, 0 = stable/growing revenue)
2. **Feature Sources**:
   - `billing_invoices`: monthly_charge trend (current vs 3-month average), overage_amount trend, payment regularity
   - `cdr_call_records`: usage_trend_3m (declining usage precedes revenue decline), data_usage_gb trend, calls_per_day trend
   - `crm_customers`: contract_end_date proximity (contract renewal = downgrade risk), plan_code, plan_data_allowance
   - `app_events`: change_plan event frequency, login decline
   - `network_measurements`: speed_test_avg (dissatisfaction signal)
3. **Model Requirements**:
   - Train via `train_multi()` (LR, RF, GB)
   - Disagreement tracking enabled — high-divergence customers may be in transitional states worth manual review
   - AUC-ROC > 0.70 on test set
   - Top features should include: usage_trend_3m, monthly_charge delta, contract proximity, change_plan events
4. **Mock Data**:
   - Generate `arpu_decline_flag` with ~10-15% decline rate
   - Correlate with: declining usage trends, contract nearing end, reduced app engagement, change_plan events
   - Include ~12% "false signals" (customers whose usage dips temporarily but recover — e.g., vacation patterns)
5. **Output**:
   - Predictions stored in `ml.model_runs` with `target_variable = 'arpu_decline_flag'`
   - Per-customer decline probability for proactive offer targeting
   - Disagree-flagged customers routed to manual review queue
6. **Tests**:
   - Dataset builds without error
   - Model trains and persists results
   - AUC-ROC above chance
   - Feature importances populated

## Definition of Done
- [ ] Mock data generator produces `arpu_decline_flag` with realistic correlations
- [ ] YAML metric definition created: `definitions/metrics/arpu_decline_flag.yaml`
- [ ] `train_multi()` works with `target_variable='arpu_decline_flag'`
- [ ] Disagreement tracking and champion/challenger governance apply
- [ ] Tests pass (all existing + new)
- [ ] DQ checks cover the new metric

## Priority
**Medium-High** — significant business value but requires more feature engineering than Payment Default

## Estimated Complexity
**Medium-High** — needs billing trend computation and careful definition of the "decline" threshold; benefits from the multi-model approach since decline patterns vary by customer segment

## Cross-Model Insights
When all three models (Churn, Payment Default, ARPU Decline) are operational, the disagreement tracking becomes especially valuable:
- A customer flagged by both **Churn** and **ARPU Decline** models is a high-priority save target
- A customer flagged by **Payment Default** but NOT **Churn** may be experiencing temporary financial difficulty — different intervention needed
- Cross-model correlation analysis can reveal systemic issues (e.g., a price increase driving both ARPU decline and churn in the same segment)
