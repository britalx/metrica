"""Entry point for Metrica DQ scheduler.

Usage:
    python3 scripts/run_scheduler.py --once              # Single run (for cron)
    python3 scripts/run_scheduler.py --once --dry-run    # Dry run
    python3 scripts/run_scheduler.py --daemon            # Loop mode
    python3 scripts/run_scheduler.py --daemon --interval 30  # Custom interval
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path for script imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from metrica.monitoring.scheduler import DQScheduler


def main():
    parser = argparse.ArgumentParser(description="Metrica DQ Scheduler")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run once and exit (cron mode)")
    mode.add_argument("--daemon", action="store_true", help="Run on schedule (daemon mode)")
    parser.add_argument("--interval", type=int, help="Override interval in minutes (daemon mode)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without writing")
    parser.add_argument(
        "--config", type=str, default="dq_schedule.yaml", help="Path to schedule config"
    )
    args = parser.parse_args()

    config_path = PROJECT_ROOT / args.config
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        sys.exit(1)

    scheduler = DQScheduler(config_path=config_path, project_root=PROJECT_ROOT)

    if args.once:
        result = scheduler.run_once(dry_run=args.dry_run)
        if result.error:
            print(f"[scheduler] Run failed: {result.error}", file=sys.stderr)
            sys.exit(1)
        status = result.overall_status.value.upper()
        print(f"[scheduler] {status} — {result.checks_run} checks, "
              f"{result.pass_count}P/{result.warn_count}W/{result.fail_count}F "
              f"in {result.duration_seconds:.1f}s"
              + (f" — alert written to {scheduler.alerts_dir}" if result.alert_written else ""))
    elif args.daemon:
        scheduler.run_daemon(interval_override=args.interval)


if __name__ == "__main__":
    main()
