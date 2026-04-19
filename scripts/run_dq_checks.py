"""DQ runner: executes DQ checks against mock data and prints a scorecard.

Usage:
    python3 scripts/run_dq_checks.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from metrica.dq.models import DQConfig, DQDimension, DQRule, Severity
from metrica.registry.loader import DefinitionLoader

_dq_config = DQConfig()

DB_PATH = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"
DEFINITIONS_ROOT = Path(__file__).parent.parent / "definitions"


# Simplified DQ check expressions that work against our actual schema.
# The YAML check_expressions are documentation-grade SQL; these are executable.
EXECUTABLE_CHECKS: dict[str, str] = {
    # tenure_months
    "tenure_months_completeness": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN tenure_months IS NULL THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
    """,
    "tenure_months_validity_range": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN tenure_months < 0 OR tenure_months > 600 THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
        WHERE tenure_months IS NOT NULL
    """,
    "tenure_months_accuracy_vs_activation": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN ABS(m.tenure_months -
                   DATEDIFF('month', c.activation_date, DATE '2026-03-15')) > 1
                   THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics m
        JOIN raw.crm_customers c ON m.customer_id = c.customer_id
        WHERE c.activation_date IS NOT NULL AND m.tenure_months IS NOT NULL
    """,
    # monthly_charges
    "monthly_charges_completeness": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN monthly_charges IS NULL THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
    """,
    "monthly_charges_validity_range": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN monthly_charges < 0 OR monthly_charges > 10000 THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
        WHERE monthly_charges IS NOT NULL
    """,
    "monthly_charges_consistency_billing": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN ABS(m.monthly_charges - b.monthly_charge_amount) >= 0.01
                   THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics m
        JOIN raw.billing_invoices b ON m.customer_id = b.customer_id
    """,
    "monthly_charges_timeliness": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN b.invoice_date < DATE '2026-03-15' - INTERVAL 35 DAY
                   THEN 1 ELSE 0 END) AS failed
        FROM raw.billing_invoices b
    """,
    # support_calls_30d
    "support_calls_30d_completeness": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN support_calls_30d IS NULL THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
    """,
    "support_calls_30d_validity_range": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN support_calls_30d < 0 OR support_calls_30d > 500 THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
    """,
    "support_calls_30d_timeliness": """
        SELECT 1 AS total,
               CASE WHEN MAX(interaction_date) < DATE '2026-03-15' - INTERVAL 2 DAY
                    THEN 1 ELSE 0 END AS failed
        FROM raw.contact_center_interactions
        WHERE interaction_type = 'call'
    """,
    "support_calls_30d_consistency_src": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN m.support_calls_30d != COALESCE(cc.actual, 0)
                   THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics m
        LEFT JOIN (
            SELECT customer_id, COUNT(*) AS actual
            FROM raw.contact_center_interactions
            WHERE interaction_type = 'call'
              AND interaction_date >= DATE '2026-02-13'
            GROUP BY customer_id
        ) cc ON m.customer_id = cc.customer_id
    """,
    # avg_signal_strength_home (network)
    "avg_signal_strength_home_completeness": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN avg_signal_strength_home IS NULL THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
    """,
    "avg_signal_strength_home_validity": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN avg_signal_strength_home < -140 OR avg_signal_strength_home > -44
                   THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
        WHERE avg_signal_strength_home IS NOT NULL
    """,
    # dropped_call_rate (CDR)
    "dropped_call_rate_validity": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN dropped_call_rate < 0 OR dropped_call_rate > 1
                   THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
        WHERE dropped_call_rate IS NOT NULL
    """,
    # login_app_frequency (app)
    "login_app_frequency_validity": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN login_app_frequency < 0 THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
        WHERE login_app_frequency IS NOT NULL
    """,
    # days_since_last_login (app)
    "days_since_last_login_validity": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN days_since_last_login < 0 OR days_since_last_login > 365
                   THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
        WHERE days_since_last_login IS NOT NULL
    """,
    # data_usage_gb (CDR)
    "data_usage_gb_completeness": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN data_usage_gb IS NULL THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
    """,
    # outage_events_experienced (network)
    "outage_events_experienced_validity": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN outage_events_experienced < 0 THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
        WHERE outage_events_experienced IS NOT NULL
    """,
    # speed_test_avg_mbps (network)
    "speed_test_avg_mbps_validity": """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN speed_test_avg_mbps < 0 OR speed_test_avg_mbps > 1000
                   THEN 1 ELSE 0 END) AS failed
        FROM metrics.customer_metrics
        WHERE speed_test_avg_mbps IS NOT NULL
    """,
}


def compute_severity(
    score: float,
    warn: float = _dq_config.default_warn_threshold,
    fail: float = _dq_config.default_fail_threshold,
) -> Severity:
    if score >= warn:
        return Severity.PASS
    elif score >= fail:
        return Severity.WARN
    return Severity.FAIL


def severity_icon(sev: Severity) -> str:
    return {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[sev.value]


def run_dq_checks(db_path: Path | None = None, definitions_root: Path | None = None) -> list[dict]:
    """Run all DQ checks and return results. Also persists to DQ tables."""
    db = db_path or DB_PATH
    defs = definitions_root or DEFINITIONS_ROOT

    conn = duckdb.connect(str(db))
    loader = DefinitionLoader(defs)
    all_rules = loader.metric_dq_rules()

    now = datetime.now(UTC)
    results = []
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    # Start score_id from current max to avoid PK collisions on re-runs
    max_id_row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM dq.dq_scores").fetchone()
    score_id = max_id_row[0]

    for metric_id, rules in all_rules.items():
        metric_scores = []

        for rule in rules:
            sql = EXECUTABLE_CHECKS.get(rule.rule_id)
            if not sql:
                continue

            row = conn.execute(sql).fetchone()
            total, failed = row[0], row[1]

            if total == 0:
                score = 1.0
            else:
                score = round(1.0 - (failed / total), 4)

            sev = compute_severity(score, warn=rule.warn_threshold, fail=rule.fail_threshold)
            metric_scores.append(score)

            result = {
                "metric_id": metric_id,
                "rule_id": rule.rule_id,
                "dimension": rule.dimension.value,
                "score": score,
                "severity": sev.value,
                "total": total,
                "failed": failed,
            }
            results.append(result)

            # Persist to DQ tables
            score_id += 1
            conn.execute(
                "INSERT INTO dq.dq_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [score_id, run_id, rule.rule_id, metric_id, rule.dimension.value,
                 score, sev.value, total, failed, "", now],
            )

        # Record aggregate run per metric
        composite = sum(metric_scores) / len(metric_scores) if metric_scores else 0.0
        overall = compute_severity(composite)
        metric_run_id = f"{run_id}-{metric_id}"
        conn.execute(
            "INSERT INTO dq.dq_runs VALUES (?, ?, ?, ?, ?, ?)",
            [metric_run_id, metric_id, round(composite, 4), overall.value, now, now],
        )

    conn.close()
    return results


def print_scorecard(results: list[dict]):
    """Print a formatted DQ scorecard to stdout."""
    header = f"{'Metric':<22} {'Dimension':<15} {'Score':>7}  {'Status':<6}"
    sep = "-" * len(header)

    print()
    print("=" * len(header))
    print("  METRICA DQ SCORECARD")
    print("=" * len(header))
    print(header)
    print(sep)

    for r in results:
        icon = severity_icon(Severity(r["severity"]))
        print(f"{r['metric_id']:<22} {r['dimension']:<15} {r['score']:>7.3f}  {icon}")

    print(sep)

    # Overall summary
    scores = [r["score"] for r in results]
    avg = sum(scores) / len(scores) if scores else 0
    print(f"{'OVERALL':<22} {'composite':<15} {avg:>7.3f}  {severity_icon(compute_severity(avg))}")
    print("=" * len(header))
    print()


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run `python3 scripts/generate_mock_data.py` first.")
        return

    results = run_dq_checks()
    print_scorecard(results)
    print(f"DQ scores persisted to {DB_PATH}")


if __name__ == "__main__":
    main()
