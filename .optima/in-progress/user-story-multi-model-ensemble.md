# User Story: Independent Multi-Model Churn Prediction with Disagreement Tracking

**Story ID:** METRICA-ENS-001
**Created by:** Brainstorming Agent
**Date:** 2026-04-19
**Status:** Draft — Pending Alex Review
**Origin:** Discussion #1 & #2 debate between Main Agent and Brainstorming Agent

---

## Epic

As a **data science team**, we want to train and compare multiple ML models independently for churn prediction, so that we can identify model disagreements, govern model selection, and surface actionable insights for the retention team.

---

## Background & Decision Context

The current Metrica ML pipeline supports a single LogisticRegression model (`ChurnModelTrainer.train_baseline()`). Through a structured debate (Discussion #1 and #2), the following was established:

- **VotingClassifier rejected** — sacrifices per-model observability that Metrica's architecture depends on (DQ gates, feature importances, per-model evaluation tracking in `ml.model_runs`)
- **Stacking deferred** — requires 10k+ customers to justify nested cross-validation overhead; current mock data is 1000 rows
- **Independent multi-model with disagreement tracking agreed** — preserves observability, adds the most actionable signal (where models disagree), enables champion/challenger governance

---

## Phase 0: Improve Mock Data Realism

### Story 0.1 — Add noise and non-linear patterns to mock data generator

**As a** data scientist,
**I want** the mock data generator to produce realistic, imperfect data,
**so that** different ML models have a genuine reason to diverge in their predictions.

**Acceptance Criteria:**
- [ ] 10-15% of churners have high satisfaction / low complaint profiles (simulating competitor poaching, not service dissatisfaction)
- [ ] Add interaction effects: e.g., `high tenure + sudden bill increase` = high churn risk, but `high tenure` alone = low risk
- [ ] Add seasonal noise to CDR and Network data (not all features monotonically correlated with churn)
- [ ] LogisticRegression AUC should drop from ~1.000 to a more realistic range (0.70-0.85) on the improved mock data
- [ ] All existing tests still pass with the updated data generator

**Files impacted:**
- `scripts/generate_mock_data.py`
- `tests/test_mock_data.py`
- `tests/test_extended_mock_data.py`

Alex Note added: if we are adding imperfect data, I would rather have an indicator for them, the original set of perfect data, could be set as pmd (perfect mock data), and we can delut the data with random (imperfect data), we can then set the level of total imperfection percent for the model disagreement impact and next steps. many thanks.

---

## Phase 1: Independent Multi-Model Training

### Story 1.1 — Add `train_multi()` method to ChurnModelTrainer

**As a** data scientist,
**I want** to train multiple models (LogisticRegression, RandomForest, GradientBoosting) on the same train/test split with the same scaler and DQ gate,
**so that** I can compare model performance on identical data conditions.

**Acceptance Criteria:**
- [ ] New `train_multi()` method in `metrica/ml/trainer.py`
- [ ] Trains at minimum: LogisticRegression, RandomForestClassifier, GradientBoostingClassifier
- [ ] All models share the same `train_test_split`, `StandardScaler`, and DQ gate results
- [ ] Each model produces its own `ModelRunResult` with individual evaluation metrics and feature importances
- [ ] Returns a list of `ModelRunResult` objects (one per model)
- [ ] Feature importances: coefficients for LR, `feature_importances_` for tree-based models
- [ ] Existing `train_baseline()` remains unchanged (backward compatible)

**Files impacted:**
- `metrica/ml/trainer.py`
- `metrica/ml/__init__.py`

### Story 1.2 — Add `run_group_id` to ModelRunResult and ml.model_runs

**As a** data scientist,
**I want** model runs from the same multi-model training session to be linked by a shared group ID,
**so that** I can query and compare models that were trained on identical data.

**Acceptance Criteria:**
- [ ] Add `run_group_id: str | None` field to `ModelRunResult` (default `None` for single-model runs)
- [ ] Add `run_group_id VARCHAR` column to `ml.model_runs` table
- [ ] `train_multi()` generates a shared `run_group_id` for all models in the group
- [ ] `train_baseline()` continues to work with `run_group_id = None`
- [ ] Schema migration is backward compatible (nullable column)

**Files impacted:**
- `metrica/ml/models.py`
- `metrica/ml/trainer.py`
- `sql/004_ml_schema.sql`

---

## Phase 2: Disagreement Tracking

### Story 2.1 — Build disagreement matrix output

**As a** retention team analyst,
**I want** to see which customers have divergent predictions across models,
**so that** I can prioritize human review for ambiguous cases.

**Acceptance Criteria:**
- [ ] After `train_multi()`, compute per-customer prediction probabilities from each model
- [ ] Identify customers where model predictions diverge by >0.3 probability (configurable threshold)
- [ ] Return a disagreement report: `customer_id`, per-model probabilities, max divergence, flag
- [ ] Optionally persist disagreement data to a new `ml.model_disagreements` table
- [ ] Include disagreement summary in the training output (count of flagged customers, % of total)

**Files impacted:**
- `metrica/ml/trainer.py` (new method or extended `train_multi()` output)
- `metrica/ml/models.py` (new `DisagreementRecord` model)
- `sql/004_ml_schema.sql` (optional new table)

---

## Phase 3: Champion/Challenger Governance

### Story 3.1 — Designate champion model and track challenger performance

**As a** ML operations engineer,
**I want** to designate one model as the production "champion" and track challengers against it,
**so that** I can swap models when a challenger consistently outperforms.

**Acceptance Criteria:**
- [ ] Add `is_champion: bool` flag to `ModelRunResult` and `ml.model_runs`
- [ ] First model trained becomes champion by default; subsequent runs are challengers
- [ ] Provide a method to compare champion vs. challengers on key metrics (AUC, F1, precision, recall)
- [ ] Provide a method to promote a challenger to champion (swap the flag)
- [ ] Champion designation persists across training sessions

**Files impacted:**
- `metrica/ml/models.py`
- `metrica/ml/trainer.py`
- `sql/004_ml_schema.sql`

---

## Future (Deferred): Stacking Ensemble

### Story F.1 — Stacking ensemble with meta-learner

**Prerequisite:** Real customer data reaches 10k+ rows.

**As a** data scientist,
**I want** to train a meta-learner on base model outputs using nested cross-validation,
**so that** I can produce a combined prediction that's better than any individual model.

_Details to be defined when prerequisite is met._

---

## Testing Requirements

- All new functionality must have unit tests in `tests/test_churn_model.py`
- Phase 0 mock data changes must not break existing pipeline tests
- Integration test: `generate_mock_data → run_pipeline → train_multi → disagreement_report` end-to-end
- Backward compatibility: `train_baseline()` must produce identical results to current behavior

---

## Dependencies

- No new Python packages required (RandomForest and GradientBoosting are in scikit-learn)
- XGBoost is optional / deferred (not required for Phase 1)
- DuckDB schema changes are additive (new nullable columns, new tables)

---

## Definition of Done

- [ ] All phases implemented with passing tests
- [ ] `ml.model_runs` schema updated with `run_group_id` and `is_champion`
- [ ] Mock data produces realistic model differentiation (LR AUC < 0.85)
- [ ] Disagreement matrix identifies at least some customers with >0.3 probability divergence
- [ ] Documentation updated in ARCHITECTURE.md
- [ ] All existing tests pass (no regressions)
