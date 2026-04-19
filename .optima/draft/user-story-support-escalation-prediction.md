# User Story: Support Escalation Prediction

## Title
As a **contact center manager**, I want to predict which customer interactions are likely to escalate (transferred to supervisor, formal complaint, or repeat contact within 48h), so that I can assign experienced agents upfront and reduce escalation rates.

## Background
Escalated interactions cost 3-5x more than standard ones and damage customer satisfaction. Currently, escalations are handled reactively. Predicting escalation risk at the start of an interaction enables intelligent routing — sending high-risk customers to senior agents immediately.

## Acceptance Criteria

1. **Target Variable**: `escalation_risk_7d` — binary label (1 = customer has an escalated interaction within the next 7 days, 0 = no escalation)
2. **Feature Sources**:
   - `contact_center_interactions`: recent interaction count, interaction_type distribution, CSAT scores, existing escalation_flag history
   - `crm_customers`: tenure, complaint_category history, ticket_status (open/unresolved), NPS response
   - `billing_invoices`: recent overage, charge increases
   - `network_measurements`: signal strength, outage events (network issues drive complaints)
   - `cdr_call_records`: dropped call rate (service quality frustration)
3. **Model Requirements**:
   - Train via `train_multi()` (LR, RF, GB)
   - Disagreement tracking enabled
   - AUC-ROC > 0.70 on test set
   - Top features should include: recent interaction frequency, CSAT trend, open ticket count, network quality
4. **Mock Data**:
   - Generate `escalation_risk_7d` with ~6-10% escalation rate
   - Correlate with: multiple recent interactions, low CSAT, open tickets, poor network metrics, high dropped call rate
   - Include ~10% "surprise" escalations (previously happy customers with sudden issues)
5. **Output**:
   - Predictions stored in `ml.model_runs` with `target_variable = 'escalation_risk_7d'`
   - Per-customer escalation probability for real-time routing decisions
6. **Tests**:
   - Dataset builds without error
   - Model trains and persists results
   - AUC-ROC above chance
   - Feature importances populated

## Definition of Done
- [ ] Mock data generator produces `escalation_risk_7d` with realistic correlations
- [ ] YAML metric definition created: `definitions/metrics/escalation_risk_7d.yaml`
- [ ] `train_multi()` works with `target_variable='escalation_risk_7d'`
- [ ] Disagreement tracking and champion/challenger governance apply
- [ ] Tests pass (all existing + new)
- [ ] DQ checks cover the new metric

## Priority
**High** — direct operational cost savings, strong data availability

## Estimated Complexity
**Medium** — contact center data is already rich; main work is deriving the escalation label from interaction patterns and parameterizing the trainer
