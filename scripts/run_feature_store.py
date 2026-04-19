"""CLI entry point for the Metrica Feature Store.

Usage:
    python3 scripts/run_feature_store.py --gate-status
    python3 scripts/run_feature_store.py --customer CUST-0001
    python3 scripts/run_feature_store.py --export-csv data/churn_features.csv
    python3 scripts/run_feature_store.py --export-csv data/churn_features_raw.csv --no-gate
    python3 scripts/run_feature_store.py --summary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from metrica.ml_bridge.feature_store import FeatureStore
from metrica.ml_bridge.exporter import export_to_csv, export_summary

DB_PATH = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"
DEFINITIONS_ROOT = Path(__file__).parent.parent / "definitions"


def print_gate_status(store: FeatureStore) -> None:
    report = store.gate_status()

    print("Metrica Feature Store — DQ Gate Status")
    print("=" * 39)
    print(
        f"Gate threshold: {report.gate_threshold:.2f}  |  "
        f"{report.passing} passing  |  "
        f"{report.blocked} blocked  |  "
        f"{report.unknown} unknown"
    )

    blocked = [e for e in report.entries if not e.passes_gate]
    if blocked:
        print(f"\nBLOCKED metrics (DQ score < {report.gate_threshold:.2f}):")
        for e in blocked:
            dim_info = f"  blocking={e.blocking_dimension}" if e.blocking_dimension else ""
            print(f"  ✗ {e.metric_id:<30} composite={e.latest_dq_score:.3f}{dim_info}")

    passing = [e for e in report.entries if e.passes_gate and e.latest_dq_score is not None]
    if passing:
        print(f"\nPASSING metrics ({len(passing)}):")
        for e in passing[:5]:
            print(f"  ✓ {e.metric_id:<30} composite={e.latest_dq_score:.3f}")
        if len(passing) > 5:
            print(f"  ... and {len(passing) - 5} more")

    unknown = [e for e in report.entries if e.latest_dq_score is None]
    if unknown:
        print(f"\nUNKNOWN metrics (no DQ score yet, {len(unknown)}):")
        for e in unknown[:5]:
            print(f"  ? {e.metric_id:<30} (no DQ run recorded)")
        if len(unknown) > 5:
            print(f"  ... and {len(unknown) - 5} more")


def print_customer_features(store: FeatureStore, customer_id: str, enforce_gate: bool) -> None:
    vector = store.get_features(customer_id, enforce_dq_gate=enforce_gate)

    print(f"Feature Vector: {vector.customer_id}")
    print("=" * (16 + len(vector.customer_id)))

    for fv in vector.features:
        if fv.gated_out:
            score_str = f"DQ score {fv.dq_score:.3f}" if fv.dq_score is not None else "no DQ"
            print(f"  {fv.metric_id:<30} ✗ GATED  ({score_str} < gate {vector.dq_gate_threshold:.2f})")
        elif fv.dq_status == "unknown":
            val = fv.value if fv.value is not None else "NULL"
            print(f"  {fv.metric_id:<30} ?  {val}   (unknown DQ)")
        else:
            val = fv.value if fv.value is not None else "NULL"
            print(f"  {fv.metric_id:<30} ✓  {val}")

    print(
        f"Served: {vector.metrics_served}/{vector.metrics_requested} metrics  |  "
        f"Gated: {vector.metrics_gated}  |  "
        f"Unknown: {sum(1 for f in vector.features if f.dq_status == 'unknown')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Metrica Feature Store CLI")
    parser.add_argument("--gate-status", action="store_true", help="Show DQ gate pass/block/unknown")
    parser.add_argument("--customer", type=str, help="Show feature vector for a customer ID")
    parser.add_argument("--export-csv", type=str, help="Export feature matrix to CSV")
    parser.add_argument("--summary", action="store_true", help="Show feature matrix summary stats")
    parser.add_argument("--no-gate", action="store_true", help="Disable DQ gate enforcement")

    args = parser.parse_args()

    if not any([args.gate_status, args.customer, args.export_csv, args.summary]):
        parser.print_help()
        sys.exit(1)

    store = FeatureStore(DB_PATH, DEFINITIONS_ROOT)
    enforce_gate = not args.no_gate

    if args.gate_status:
        print_gate_status(store)

    if args.customer:
        print_customer_features(store, args.customer, enforce_gate)

    if args.export_csv:
        matrix = store.get_feature_matrix(enforce_dq_gate=enforce_gate)
        path = export_to_csv(matrix, Path(args.export_csv))
        print(f"Exported {matrix.total_customers} customers × {len(matrix.metrics_served)} metrics → {path}")

    if args.summary:
        matrix = store.get_feature_matrix(enforce_dq_gate=enforce_gate)
        print(export_summary(matrix))


if __name__ == "__main__":
    main()
