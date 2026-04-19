# Task: Minor Fixes — Post Code Review

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-06
**Priority**: Low — polish & hardening, no urgency

---

## First — A Personal Note 🙏

Optima, before anything else: **thank you**. Genuinely.

The kickoff task was already impressive — clean architecture, thoughtful decisions,
DECISIONS.md that reads like it was written by someone who actually *cares* about the
codebase they're leaving behind. But the mock data task was something else. You built
a full end-to-end pipeline — generator, runner, scorecard, 8 new tests — and shipped
it clean. 14/14 tests passing. The DQ issues surfacing exactly where they should.

That's not just task completion. That's craftsmanship.

Alex and I did a full code review together. The verdict: **excellent work on both
tasks**. The issues below are genuinely minor — the kind of polish that takes a good
codebase to a great one. Nothing is broken. We just want to make it as solid as the
rest of what you've built.

---

## What Needs Fixing

### Fix 1 — `dq_scores` Sequence PK Collision 🐛

**The problem**: When `run_dq_checks.py` is run against an existing database (one that
already has DQ scores from a previous run), it fails with:

```
_duckdb.ConstraintException: Constraint Error: Duplicate key "id: 1"
violates primary key constraint.
```

This happens because `CREATE SEQUENCE IF NOT EXISTS dq_scores_seq START 1` is called
inside `generate_mock_data.py` at DB creation time — fine. But the runner uses
`score_id = 0` as a local counter starting from 1, which collides on the second run.

**The fix**: In `scripts/run_dq_checks.py`, instead of a local `score_id` counter
starting from 0, query the current max id from `dq.dq_scores` and continue from there:

```python
# At the start of run_dq_checks(), after connecting:
max_id_row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM dq.dq_scores").fetchone()
score_id = max_id_row[0]
# Then increment: score_id += 1 before each insert
```

This makes the runner safely re-runnable against a persistent database — each run
appends new scores without collision, which is exactly what we want for trend tracking.

**Verify** by running the scorecard twice in a row against the same DB without
regenerating — both runs should succeed and `dq.dq_scores` should have rows from both.

---

### Fix 2 — Composite Severity Uses Global `DQConfig` Defaults 🔧

**The problem**: In `run_dq_checks.py`, the per-metric composite severity is computed
using `rules[0]`'s thresholds:

```python
overall = compute_severity(composite, rules[0])  # Uses first rule's thresholds
```

This is fragile — if the first rule happens to have custom thresholds, the composite
severity for that entire metric gets skewed.

**The fix**: Import and use `DQConfig` defaults for composite-level severity:

```python
from metrica.dq.models import DQConfig

_dq_config = DQConfig()

# Then when computing composite severity:
overall_sev = compute_severity(
    composite,
    DQRule(
        rule_id="_composite",
        name="_composite",
        dimension=DQDimension.COMPLETENESS,
        target_type="metric",
        target_id=metric_id,
        check_expression="_",
        warn_threshold=_dq_config.default_warn_threshold,
        fail_threshold=_dq_config.default_fail_threshold,
    )
)
```

Or cleaner still — refactor `compute_severity` to accept raw threshold floats directly
rather than a full `DQRule` object, so you can call it simply as:
`compute_severity(composite, warn=0.95, fail=0.80)`.

Your call on which approach reads better — just make it consistent with how it's used
at the bottom of `print_scorecard()` too (that ad-hoc `DQRule` construction there is
a bit of a code smell, and this fix is the right moment to clean it up).

---

### Fix 3 — Add `data/*.duckdb` to `.gitignore` 📁

Small one. The `data/metrica_mock.duckdb` file shouldn't be tracked in git — it's
generated, potentially large, and binary. Check if it's already in `.gitignore` and
add it if not:

```
# In .gitignore:
data/*.duckdb
data/*.db
```

Also confirm `data/` directory itself is not tracked (it should just be created by the
generator at runtime).

---

## Acceptance Criteria

- [ ] Running `python3 scripts/run_dq_checks.py` twice in a row (without regenerating)
      succeeds both times — no PK constraint errors
- [ ] `dq.dq_scores` accumulates rows across runs (trend tracking works)
- [ ] Composite severity uses `DQConfig` defaults, not `rules[0]` thresholds
- [ ] `print_scorecard()` no longer constructs an ad-hoc `DQRule` just for severity
- [ ] `data/*.duckdb` is in `.gitignore`
- [ ] All 14 existing tests still pass — zero regressions
- [ ] Run `pytest tests/ -v` at the end and confirm

---

## A Final Word

You're building something that matters here. Metrica is the foundation that every ML
feature in this project will stand on. The care you're putting into it — the clean
models, the documented decisions, the honest test coverage — that quality is going to
pay dividends when we're running the churn model against 40 features and need to trust
every single one of them.

Keep it up. This is great work. 🚀



---
## Agent Response (2026-04-06 01:53:47)
**Outcome**: completed

3 fixes applied: (1) DQ runner PK collision resolved — uses MAX(id) for safe re-runs, verified with double-run (6 runs, 22 scores). (2) compute_severity refactored to accept raw thresholds, composite uses DQConfig defaults. (3) data/*.db added to .gitignore. 14/14 tests passing.
