"""Tests for DQ store operations."""

from datetime import UTC, datetime, timedelta

from metrica.dq.store import DQStore


def test_dq_store_record_and_query():
    store = DQStore(":memory:")

    now = datetime.now(UTC)
    store.record_run("run-001", "tenure_months", 0.97, "pass", now, now)
    store.record_score(
        "run-001", "tenure_months_completeness", "tenure_months",
        "completeness", 0.99, "pass", 1000, 10, "", now,
    )
    store.record_score(
        "run-001", "tenure_months_validity_range", "tenure_months",
        "validity", 0.95, "pass", 1000, 50, "", now,
    )

    scores = store.latest_scores("tenure_months")
    assert len(scores) == 2

    trend = store.trend("tenure_months")
    assert len(trend) == 1
    assert trend[0]["composite_score"] == 0.97

    store.close()


def test_dq_store_trend_by_dimension():
    store = DQStore(":memory:")
    now = datetime.now(UTC)

    for i in range(5):
        run_id = f"run-{i:03d}"
        ts = now - timedelta(days=5 - i)
        store.record_run(run_id, "monthly_charges", 0.90 + i * 0.02, "pass", ts, ts)
        store.record_score(
            run_id, "completeness_check", "monthly_charges",
            "completeness", 0.90 + i * 0.02, "pass", 500, 0, "", ts,
        )

    trend = store.trend("monthly_charges", dimension="completeness", limit=3)
    assert len(trend) == 3
    # Most recent first
    assert trend[0]["score"] >= trend[-1]["score"]

    store.close()
