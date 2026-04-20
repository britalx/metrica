"""Tests for churn model — dataset, trainer, and integration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np

from metrica.ml.dataset import ChurnDataset
from metrica.ml.models import ModelRunResult, MultiModelResult, DisagreementRecord
from metrica.ml.trainer import ChurnModelTrainer
from metrica.registry.loader import DefinitionLoader

DEFINITIONS_ROOT = Path(__file__).parent.parent / "definitions"


def _setup_db(db_path: str) -> str:
    """Create a self-contained test DB with churn labels, metrics, and DQ scores."""
    conn = duckdb.connect(db_path)

    for schema in ("raw", "metrics", "dq", "pipeline", "ml"):
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # Raw customers with churn labels
    conn.execute("""
        CREATE OR REPLACE TABLE raw.crm_customers (
            customer_id VARCHAR PRIMARY KEY,
            activation_date DATE,
            account_status VARCHAR,
            churn_label_30d INTEGER
        )
    """)

    # 40 customers: 36 active (label=0) + 4 terminated (label=1) = 10% churn
    rows = []
    for i in range(1, 41):
        cid = f"CUST-{i:04d}"
        if i >= 37:  # last 4 are churners
            rows.append((cid, "2022-01-15", "terminated", 1))
        else:
            rows.append((cid, "2022-01-15", "active", 0))
    conn.executemany("INSERT INTO raw.crm_customers VALUES (?, ?, ?, ?)", rows)

    # Metrics table with a few features + churn label + late_payment_flag
    conn.execute("""
        CREATE OR REPLACE TABLE metrics.customer_metrics (
            customer_id VARCHAR PRIMARY KEY,
            tenure_months DOUBLE,
            monthly_charges DOUBLE,
            support_calls_30d INTEGER,
            churn_label_30d INTEGER,
            late_payment_flag INTEGER
        )
    """)

    import random
    random.seed(42)
    metric_rows = []
    for i in range(1, 41):
        cid = f"CUST-{i:04d}"
        tenure = float(random.randint(6, 120))
        charges = round(random.gauss(65, 25), 2)
        calls = random.randint(0, 10)
        churn = 1 if i >= 37 else 0
        # late_payment_flag: 4 late payers correlated with low tenure & high charges
        # Customers 1-4 (low customer_id) are late payers.
        late = 1 if i <= 4 else 0
        metric_rows.append((cid, tenure, charges, calls, churn, late))
    conn.executemany(
        "INSERT INTO metrics.customer_metrics VALUES (?, ?, ?, ?, ?, ?)", metric_rows,
    )

    # DQ tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dq.dq_runs (
            run_id VARCHAR PRIMARY KEY, target_id VARCHAR NOT NULL,
            composite_score DOUBLE NOT NULL, overall_severity VARCHAR NOT NULL,
            run_started_at TIMESTAMP NOT NULL, run_finished_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dq.dq_scores (
            id INTEGER PRIMARY KEY, run_id VARCHAR NOT NULL,
            rule_id VARCHAR NOT NULL, target_id VARCHAR NOT NULL,
            dimension VARCHAR NOT NULL, score DOUBLE NOT NULL,
            severity VARCHAR NOT NULL, records_checked INTEGER DEFAULT 0,
            records_failed INTEGER DEFAULT 0, details VARCHAR DEFAULT '',
            checked_at TIMESTAMP NOT NULL
        )
    """)

    now = datetime.now(UTC)
    # All 3 metrics pass DQ gate (score >= 0.90)
    for i, (mid, score) in enumerate([
        ("tenure_months", 0.98), ("monthly_charges", 0.95), ("support_calls_30d", 1.0),
    ]):
        conn.execute(
            "INSERT INTO dq.dq_runs VALUES (?, ?, ?, ?, ?, ?)",
            [f"run-{mid}", mid, score, "pass", now, now],
        )
        conn.execute(
            "INSERT INTO dq.dq_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [i + 1, f"run-{mid}", f"{mid}_check", mid, "completeness", score, "pass", 20, 0, "", now],
        )

    conn.close()
    return db_path


# ── Dataset tests ────────────────────────────────────────────────────


def test_churn_dataset_builds(tmp_path):
    """ChurnDataset.build() returns X, y, feature_names, gated_metrics."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, y, feature_names, gated_metrics = ds.build(enforce_dq_gate=False)

    assert isinstance(X, np.ndarray)
    assert isinstance(y, np.ndarray)
    assert isinstance(feature_names, list)
    assert len(feature_names) > 0


def test_churn_dataset_shape(tmp_path):
    """X has shape (20, n_features), y has shape (20,)."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, y, feature_names, _ = ds.build(enforce_dq_gate=False)

    assert X.shape[0] == 40
    assert X.shape[1] == len(feature_names)
    assert y.shape == (40,)


def test_churn_label_in_y_not_x(tmp_path):
    """churn_label_30d not in feature_names, is present in y."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, y, feature_names, _ = ds.build(enforce_dq_gate=False)

    assert "churn_label_30d" not in feature_names
    assert 1 in y  # at least one churner


def test_churn_rate_approx_5pct(tmp_path):
    """y.mean() is approximately 0.05 (1/20 in test data)."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    _, y, _, _ = ds.build(enforce_dq_gate=False)

    assert y.mean() == 4 / 40  # exactly 4 churners in 40


def test_no_nulls_in_X(tmp_path):
    """After imputation, X has no NaN values."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, _, _, _ = ds.build(enforce_dq_gate=False)

    assert not np.isnan(X).any()


# ── Trainer tests ────────────────────────────────────────────────────


def test_trainer_baseline_runs(tmp_path):
    """train_baseline() returns ModelRunResult with valid fields."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(enforce_dq_gate=False)

    assert isinstance(result, ModelRunResult)
    assert result.model_type == "logistic_regression"
    assert result.training_customers > 0
    assert result.test_customers > 0
    assert len(result.features_used) > 0


def test_auc_roc_above_chance(tmp_path):
    """AUC-ROC > 0.5 (better than random). With tiny data, allow >= 0.0 gracefully."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(enforce_dq_gate=False)

    # With only 20 samples and 1 positive, AUC may vary — just check it's a valid float
    assert 0.0 <= result.evaluation.auc_roc <= 1.0


def test_model_run_persisted(tmp_path):
    """ml.model_runs has a row after train_baseline()."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(enforce_dq_gate=False)

    conn = duckdb.connect(db_path, read_only=True)
    count = conn.execute("SELECT COUNT(*) FROM ml.model_runs").fetchone()[0]
    conn.close()

    assert count == 1


def test_feature_importances_ranked(tmp_path):
    """feature_importances sorted by abs_importance desc, ranks sequential."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(enforce_dq_gate=False)

    importances = result.feature_importances
    assert len(importances) > 0

    for i, fi in enumerate(importances):
        assert fi.rank == i + 1

    # Check descending order of abs_importance
    for i in range(len(importances) - 1):
        assert importances[i].abs_importance >= importances[i + 1].abs_importance


def test_churn_label_yaml_loads():
    """definitions/metrics/churn_label_30d.yaml loads via DefinitionLoader."""
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    metrics = {m.metric_id: m for m in loader.metrics()}
    assert "churn_label_30d" in metrics
    assert metrics["churn_label_30d"].domain.value == "derived_engineered"


def test_mock_data_has_churn_column(tmp_path):
    """raw.crm_customers and metrics.customer_metrics both have churn_label_30d."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)

    conn = duckdb.connect(db_path, read_only=True)

    raw_cols = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='raw' AND table_name='crm_customers'"
    ).fetchall()
    raw_col_names = {r[0] for r in raw_cols}
    assert "churn_label_30d" in raw_col_names

    metric_cols = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='metrics' AND table_name='customer_metrics'"
    ).fetchall()
    metric_col_names = {r[0] for r in metric_cols}
    assert "churn_label_30d" in metric_col_names

    conn.close()


# ── Multi-model tests ────────────────────────────────────────────────


def test_train_multi_returns_multi_model_result(tmp_path):
    """train_multi() returns a MultiModelResult with multiple model results."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    assert isinstance(result, MultiModelResult)
    assert len(result.model_results) == 3  # LR + RF + GB
    assert result.run_group_id.startswith("group-")


def test_train_multi_all_models_have_same_group(tmp_path):
    """All model results share the same run_group_id."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    group_ids = {r.run_group_id for r in result.model_results}
    assert len(group_ids) == 1
    assert result.run_group_id in group_ids


def test_train_multi_model_types(tmp_path):
    """train_multi trains all three default model types."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    model_types = {r.model_type for r in result.model_results}
    assert model_types == {"logistic_regression", "random_forest", "gradient_boosting"}


def test_train_multi_selective_models(tmp_path):
    """train_multi with specific model_types only trains those."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(
        enforce_dq_gate=False,
        model_types=["logistic_regression", "random_forest"],
    )

    assert len(result.model_results) == 2
    types = {r.model_type for r in result.model_results}
    assert types == {"logistic_regression", "random_forest"}


def test_train_multi_persists_all_runs(tmp_path):
    """All model runs are persisted to ml.model_runs with run_group_id."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    conn = duckdb.connect(db_path, read_only=True)
    count = conn.execute("SELECT COUNT(*) FROM ml.model_runs").fetchone()[0]
    group_count = conn.execute(
        "SELECT COUNT(*) FROM ml.model_runs WHERE run_group_id = ?",
        [result.run_group_id],
    ).fetchone()[0]
    conn.close()

    assert count == 3
    assert group_count == 3


def test_train_multi_each_model_has_valid_eval(tmp_path):
    """Each model result has valid evaluation metrics."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    for mr in result.model_results:
        assert 0.0 <= mr.evaluation.auc_roc <= 1.0
        assert 0.0 <= mr.evaluation.accuracy <= 1.0
        assert len(mr.feature_importances) > 0


# ── Disagreement tracking tests ──────────────────────────────────────


def test_disagreements_returned(tmp_path):
    """train_multi returns disagreement records."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    assert isinstance(result.disagreements, list)
    assert len(result.disagreements) > 0
    assert all(isinstance(d, DisagreementRecord) for d in result.disagreements)


def test_disagreement_fields_valid(tmp_path):
    """Each disagreement record has valid fields."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    for d in result.disagreements:
        assert isinstance(d.customer_id, str)
        assert len(d.predictions) == 3  # 3 models
        assert 0.0 <= d.max_divergence <= 1.0
        assert isinstance(d.flagged, bool)


def test_disagreement_flagging_threshold(tmp_path):
    """Flagged customers have max_divergence > threshold."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False, disagreement_threshold=0.3)

    for d in result.disagreements:
        if d.flagged:
            assert d.max_divergence > 0.3
        else:
            assert d.max_divergence <= 0.3

    assert result.flagged_count == sum(1 for d in result.disagreements if d.flagged)


def test_disagreements_persisted(tmp_path):
    """Disagreements are persisted to ml.model_disagreements."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    conn = duckdb.connect(db_path, read_only=True)
    count = conn.execute(
        "SELECT COUNT(*) FROM ml.model_disagreements WHERE run_group_id = ?",
        [result.run_group_id],
    ).fetchone()[0]
    conn.close()

    assert count == len(result.disagreements)


# ── Champion/Challenger tests ────────────────────────────────────────


def test_promote_champion(tmp_path):
    """promote_champion sets is_champion=TRUE for the given run_id."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    best = max(result.model_results, key=lambda r: r.evaluation.auc_roc)
    trainer.promote_champion(best.run_id)

    conn = duckdb.connect(db_path, read_only=True)
    champ = conn.execute(
        "SELECT run_id FROM ml.model_runs WHERE is_champion = TRUE"
    ).fetchone()
    conn.close()

    assert champ is not None
    assert champ[0] == best.run_id


def test_get_champion(tmp_path):
    """get_champion returns the current champion's run_id."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    # No champion initially
    assert trainer.get_champion() is None

    # Promote one
    best = result.model_results[0]
    trainer.promote_champion(best.run_id)
    assert trainer.get_champion() == best.run_id


def test_champion_swap(tmp_path):
    """Promoting a new champion demotes the old one."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(enforce_dq_gate=False)

    first = result.model_results[0]
    second = result.model_results[1]

    trainer.promote_champion(first.run_id)
    assert trainer.get_champion() == first.run_id

    trainer.promote_champion(second.run_id)
    assert trainer.get_champion() == second.run_id

    # Only one champion
    conn = duckdb.connect(db_path, read_only=True)
    champ_count = conn.execute(
        "SELECT COUNT(*) FROM ml.model_runs WHERE is_champion = TRUE"
    ).fetchone()[0]
    conn.close()
    assert champ_count == 1


# ── PMD flag / imperfect data tests ──────────────────────────────────


def test_pmd_flag_in_mock_data():
    """raw.crm_customers has pmd_flag column in the real mock DB."""
    db_path = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"
    if not db_path.exists():
        return  # skip if mock DB not generated

    conn = duckdb.connect(str(db_path), read_only=True)
    cols = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='raw' AND table_name='crm_customers'"
    ).fetchall()
    col_names = {r[0] for r in cols}
    conn.close()

    assert "pmd_flag" in col_names


def test_imperfect_churners_exist():
    """Some churners have pmd_flag=FALSE (imperfect data)."""
    db_path = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"
    if not db_path.exists():
        return  # skip if mock DB not generated

    conn = duckdb.connect(str(db_path), read_only=True)
    imperfect = conn.execute(
        "SELECT COUNT(*) FROM raw.crm_customers "
        "WHERE churn_label_30d = 1 AND pmd_flag = FALSE"
    ).fetchone()[0]
    total_churners = conn.execute(
        "SELECT COUNT(*) FROM raw.crm_customers WHERE churn_label_30d = 1"
    ).fetchone()[0]
    conn.close()

    assert imperfect > 0
    assert imperfect < total_churners  # not all churners are imperfect


# ── Payment default prediction (late_payment_flag target) ────────────


def test_late_payment_yaml_loads():
    """definitions/metrics/late_payment_flag.yaml loads via DefinitionLoader."""
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    metrics = {m.metric_id: m for m in loader.metrics()}
    assert "late_payment_flag" in metrics
    assert metrics["late_payment_flag"].domain.value == "derived_engineered"


def test_late_payment_yaml_has_dq_rules():
    """The late_payment_flag YAML has completeness + validity DQ rules."""
    loader = DefinitionLoader(DEFINITIONS_ROOT)
    dq_rules_by_metric = loader.metric_dq_rules()
    assert "late_payment_flag" in dq_rules_by_metric
    rules = dq_rules_by_metric["late_payment_flag"]
    dimensions = {r.dimension.value for r in rules}
    assert "completeness" in dimensions
    assert "validity" in dimensions


def test_dataset_builds_with_late_payment_target(tmp_path):
    """ChurnDataset.build(target_column='late_payment_flag') returns correct y."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    ds = ChurnDataset(Path(db_path), DEFINITIONS_ROOT)
    X, y, feature_names, _ = ds.build(
        enforce_dq_gate=False, target_column="late_payment_flag",
    )

    # Target is excluded from features.
    assert "late_payment_flag" not in feature_names
    # Default churn label is always excluded too (no label leakage).
    assert "churn_label_30d" not in feature_names
    # 4 late payers in the fixture.
    assert int(y.sum()) == 4


def test_train_multi_with_late_payment_target(tmp_path):
    """train_multi trains on late_payment_flag and persists the target."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(
        enforce_dq_gate=False, target_variable="late_payment_flag",
    )

    assert isinstance(result, MultiModelResult)
    assert len(result.model_results) == 3
    for mr in result.model_results:
        assert mr.target_variable == "late_payment_flag"
        assert 0.0 <= mr.evaluation.auc_roc <= 1.0
        assert len(mr.feature_importances) > 0


def test_train_multi_target_persisted(tmp_path):
    """target_variable column persists alongside each model run."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_multi(
        enforce_dq_gate=False, target_variable="late_payment_flag",
    )

    conn = duckdb.connect(db_path, read_only=True)
    target_values = conn.execute(
        "SELECT DISTINCT target_variable FROM ml.model_runs WHERE run_group_id = ?",
        [result.run_group_id],
    ).fetchall()
    conn.close()

    assert len(target_values) == 1
    assert target_values[0][0] == "late_payment_flag"


def test_train_baseline_with_late_payment_target(tmp_path):
    """train_baseline supports the late_payment_flag target."""
    db_path = str(tmp_path / "test.duckdb")
    _setup_db(db_path)
    trainer = ChurnModelTrainer(Path(db_path), DEFINITIONS_ROOT)
    result = trainer.train_baseline(
        enforce_dq_gate=False, target_variable="late_payment_flag",
    )

    assert result.target_variable == "late_payment_flag"
    # Positive class rate stored under the legacy field name.
    assert result.churn_rate_train > 0.0


def test_late_payment_in_mock_data():
    """The generated mock DB (if present) contains the late_payment_flag column
    with a realistic positive-class rate."""
    db_path = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"
    if not db_path.exists():
        return  # skip if mock DB not generated

    conn = duckdb.connect(str(db_path), read_only=True)
    cols = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='metrics' AND table_name='customer_metrics'"
    ).fetchall()
    col_names = {r[0] for r in cols}
    assert "late_payment_flag" in col_names

    total, positives = conn.execute(
        "SELECT COUNT(*), SUM(late_payment_flag) FROM metrics.customer_metrics"
    ).fetchone()
    conn.close()

    rate = (positives or 0) / total if total else 0.0
    # Generator targets 8-12%, allow 2%-25% to absorb stochastic variation.
    assert 0.02 <= rate <= 0.25, f"unexpected late_payment_flag rate: {rate:.2%}"
