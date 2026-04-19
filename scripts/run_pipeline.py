"""Entry point for Metrica ETL pipeline.

Usage:
    python3 scripts/run_pipeline.py                          # Run all metrics
    python3 scripts/run_pipeline.py --metrics tenure_months   # Specific metrics
    python3 scripts/run_pipeline.py --dry-run                # No writes
    python3 scripts/run_pipeline.py --verbose                # Detailed output
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from metrica.pipeline.models import PipelineStatus
from metrica.pipeline.runner import PipelineRunner

DB_PATH = PROJECT_ROOT / "data" / "metrica_mock.duckdb"
DEFINITIONS_ROOT = PROJECT_ROOT / "definitions"


def main():
    parser = argparse.ArgumentParser(description="Metrica ETL Pipeline")
    parser.add_argument(
        "--metrics", nargs="+", help="Specific metric IDs to run (default: all)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute without writing to DB"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print per-metric details"
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run `python3 scripts/generate_mock_data.py` first.")
        sys.exit(1)

    runner = PipelineRunner(db_path=DB_PATH, definitions_root=DEFINITIONS_ROOT)
    result = runner.run(metric_ids=args.metrics, dry_run=args.dry_run)

    # Print output
    mode = " (DRY RUN)" if args.dry_run else ""
    print(f"\nMetrica ETL Pipeline{mode}")
    print("=" * 40)
    print(f"Running {result.metrics_attempted} metrics...\n")

    for mr in result.metric_results:
        if mr.status == PipelineStatus.SUCCESS:
            icon = "ok"
            detail = f"{mr.rows_written:>5} rows" if not args.dry_run else f"{mr.rows_read:>5} rows (read)"
        else:
            icon = "FAIL"
            detail = mr.error or "unknown error"
        line = f"  {icon:<4} {mr.metric_id:<22} {detail}  ({mr.duration_seconds:.2f}s)"
        print(line)
        if args.verbose and mr.status == PipelineStatus.FAILED and mr.error:
            print(f"       Error: {mr.error}")

    print()
    status_str = f"{result.metrics_succeeded}/{result.metrics_attempted} succeeded"
    if result.metrics_failed > 0:
        status_str += f" | {result.metrics_failed} failed"
    written_str = f"{result.total_rows_written} rows written" if not args.dry_run else "dry run"
    print(f"Pipeline complete: {status_str} | {written_str} | {result.duration_seconds:.2f}s total")
    print(f"Run ID: {result.run_id}")

    if result.status == PipelineStatus.FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()
