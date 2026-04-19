"""Alert writer — generates DQ alert markdown files."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metrica.monitoring.scheduler import ScheduleRunResult


def _severity_icon(severity: str) -> str:
    return {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(severity, severity)


def write_alert(
    result: "ScheduleRunResult", dq_results: list[dict], output_dir: Path
) -> Path:
    """Write alert markdown file. Returns path to written file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = result.started_at.strftime("%Y%m%d_%H%M%S")
    status = result.overall_status.value.upper()
    filename = f"{ts}_{status}.md"
    filepath = output_dir / filename

    # Build markdown content
    lines = []
    lines.append(f"# DQ Alert — {result.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Status**: {status}")
    lines.append(f"**Run ID**: {result.run_id}")
    lines.append(f"**Duration**: {result.duration_seconds:.1f}s")
    lines.append(
        f"**Checks**: {result.checks_run} run | "
        f"{result.pass_count} pass | {result.warn_count} warn | {result.fail_count} fail"
    )
    lines.append("")

    # Warnings section
    warnings = [r for r in dq_results if r["severity"] == "warn"]
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        lines.append("| Metric | Dimension | Score |")
        lines.append("|--------|-----------|-------|")
        for w in warnings:
            lines.append(f"| {w['metric_id']} | {w['dimension']} | {w['score']:.3f} |")
        lines.append("")

    # Failures section
    failures = [r for r in dq_results if r["severity"] == "fail"]
    if failures:
        lines.append("## Failures")
        lines.append("")
        lines.append("| Metric | Dimension | Score |")
        lines.append("|--------|-----------|-------|")
        for f in failures:
            lines.append(f"| {f['metric_id']} | {f['dimension']} | {f['score']:.3f} |")
        lines.append("")

    # Full scorecard
    lines.append("## Full Scorecard")
    lines.append("")
    lines.append("| Metric | Dimension | Score | Status |")
    lines.append("|--------|-----------|-------|--------|")
    for r in dq_results:
        lines.append(
            f"| {r['metric_id']} | {r['dimension']} | {r['score']:.3f} | "
            f"{_severity_icon(r['severity'])} |"
        )
    lines.append("")

    content = "\n".join(lines)
    filepath.write_text(content)

    # Update latest.md — copy to latest.md (symlinks can be fragile on some systems)
    latest_path = output_dir / "latest.md"
    shutil.copy2(filepath, latest_path)

    return filepath
