# Task: Story 3.1 — Scheduled DQ Runner

**Delegated by**: Claude (CLite session)
**Date**: 2026-04-06
**Epic**: 3 — Monitoring & Alerting
**Priority**: High — makes Metrica self-operating

---

## Context & Where We Are

The codebase is in great shape after your last three deliveries:

- `scripts/run_dq_checks.py` — fully working DQ runner, re-runnable, scores persist cleanly
- `metrica/dq/models.py` — `DQConfig`, `DQRule`, `Severity`, `DQRunResult` all solid
- `metrica/dq/config.py` — `load_dq_config()` ready to load from YAML
- `metrica/monitoring/__init__.py` — empty stub, waiting for exactly this story
- `data/metrica_mock.duckdb` — live database with 3 metrics, 11 DQ checks, accumulating runs
- 14 tests passing

**What's missing**: the system only runs when someone manually calls
`python3 scripts/run_dq_checks.py`. This story makes it *self-operating* — DQ checks
run on a schedule, write results, and emit alerts automatically. No babysitting required.

---

## Environment Constraint — Important

This runs on **Termux ARM** (Android). That means:
- ✅ `cron` is available via Termux (`crontab -e`)
- ✅ Python `schedule` library can be pip-installed
- ✅ File-based output works perfectly
- ❌ No `systemd`, no Docker, no `launchd`
- ❌ No always-on daemon unless Termux session is open

Design for **two modes**:
1. **Cron mode** — a script that runs once and exits (invoked by cron)
2. **Daemon mode** — a long-running loop using the `schedule` library (for interactive sessions)

Both modes use the same core DQ runner. The difference is only in how they're invoked.

---

## What to Build

### 1. `metrica/monitoring/scheduler.py` — The Scheduling Engine

Core module that lives in the `monitoring` package (the stub is already there). Responsibilities:
- Load schedule configuration from `dq_schedule.yaml` (see below)
- Wrap `run_dq_checks()` with timing, error handling, and result routing
- Support both cron-invoked (single-shot) and daemon (loop) execution modes
- Write structured run summaries to `.alerts/` directory

```python
# Public interface that Optima should implement:

class DQScheduler:
    def __init__(self, config_path: Path, db_path: Path, definitions_root: Path): ...
    def run_once(self) -> ScheduleRunResult: ...        # Single shot — called by cron
    def run_daemon(self, until_stopped: bool = True): ...  # Loop — called interactively
```

`ScheduleRunResult` should be a Pydantic model capturing:
- `run_id`, `started_at`, `finished_at`, `duration_seconds`
- `metrics_checked: int`
- `checks_run: int`
- `pass_count`, `warn_count`, `fail_count`
- `overall_status: Severity`
- `alert_written: bool`

---

### 2. `dq_schedule.yaml` — Schedule Configuration (project root)

Human-readable schedule config. Keep it simple:

```yaml
# DQ Schedule Configuration
# Controls when DQ checks run and how results are handled

schedule:
  # How often to run (used in daemon mode)
  interval_minutes: 60

  # Cron expression (for reference / cron setup instructions)
  cron_expression: "0 * * * *"   # every hour

  # Run immediately on startup in daemon mode?
  run_on_start: true

database:
  path: data/metrica_mock.duckdb

definitions:
  root: definitions/

alerts:
  # Where to write alert files
  output_dir: .alerts/

  # Write a summary file after every run (pass or not)?
  write_always: false

  # Always write on WARN or FAIL
  write_on_warn: true
  write_on_fail: true

  # Print scorecard to stdout on every run?
  print_scorecard: true
```

Load this with the existing `load_dq_config()` pattern — or better, make a separate
`load_schedule_config(path)` function in `metrica/monitoring/scheduler.py` since it has
different fields than `DQConfig`.

---

### 3. `metrica/monitoring/alerting.py` — Alert Writer

Separate module for writing alert files. Clean separation from scheduling logic.

**Alert file format** — write to `.alerts/YYYYMMDD_HHMMSS_<status>.md`:

```markdown
# DQ Alert — 2026-04-06 14:00:01
**Status**: WARN
**Run ID**: run-a3f9c12b
**Duration**: 1.3s
**Checks**: 11 run | 8 pass | 3 warn | 0 fail

## Warnings

| Metric | Dimension | Score | Threshold |
|--------|-----------|-------|-----------|
| monthly_charges | validity | 0.980 | 0.990 |
| monthly_charges | timeliness | 0.867 | 0.950 |
| tenure_months | completeness | 0.950 | 0.990 |

## Full Scorecard

| Metric | Dimension | Score | Status |
|--------|-----------|-------|--------|
| monthly_charges | completeness | 1.000 | PASS |
...
```

**Public interface**:
```python
def write_alert(result: ScheduleRunResult, dq_results: list[dict], output_dir: Path) -> Path:
    """Write alert markdown file. Returns path to written file."""
```

Also write a `latest.md` symlink (or copy) in `.alerts/` that always points to the most
recent run — makes it easy to `cat .alerts/latest.md` to see the current state.

---

### 4. `scripts/run_scheduler.py` — Entry Points

Two entry points in one script, driven by CLI args:

```bash
# Cron mode — run once and exit (add this to crontab)
python3 scripts/run_scheduler.py --once

# Daemon mode — run every N minutes until stopped (from interactive session)
python3 scripts/run_scheduler.py --daemon

# Override interval (daemon mode)
python3 scripts/run_scheduler.py --daemon --interval 30

# Dry run — show what would run without writing to DB or alerts
python3 scripts/run_scheduler.py --once --dry-run
```

For **daemon mode**, use the `schedule` library:
```python
# Install in venv:
# pip install schedule
import schedule, time

schedule.every(interval_minutes).minutes.do(scheduler.run_once)
if config.run_on_start:
    scheduler.run_once()
while True:
    schedule.run_pending()
    time.sleep(30)
```

For **cron mode**, the script just calls `scheduler.run_once()` and exits. Print the
scorecard to stdout (cron captures it in mail/logs automatically).

---

### 5. `tests/test_scheduler.py` — Tests

```python
def test_schedule_config_loads():
    """dq_schedule.yaml loads into a valid config object."""

def test_run_once_returns_result():
    """run_once() returns a ScheduleRunResult with expected fields."""

def test_run_once_persists_scores():
    """After run_once(), dq.dq_scores has new rows."""

def test_alert_written_on_warn():
    """Alert file is written when a WARN is present in results."""

def test_alert_file_format():
    """Alert markdown file contains expected sections."""

def test_latest_symlink_updated():
    """latest.md in .alerts/ is updated after each run."""

def test_dry_run_does_not_write():
    """--dry-run mode does not write to DB or .alerts/."""
```

---

### 6. `README.md` — Add Scheduler Section

Add a **"Running the DQ Scheduler"** section to the existing README with:
- How to run once manually
- How to set up cron on Termux
- How to run in daemon mode
- How to read alert files
- Example crontab entry:

```
# Run Metrica DQ checks every hour
0 * * * * cd /data/data/com.termux/files/home/alex/wrks/metica && .venv/bin/python3 scripts/run_scheduler.py --once >> .logs/dq_cron.log 2>&1
```

Also mention that `.alerts/` and `.logs/` should be added to `.gitignore`.

---

## Acceptance Criteria

- [ ] `python3 scripts/run_scheduler.py --once` runs cleanly, prints scorecard, exits
- [ ] `python3 scripts/run_scheduler.py --once --dry-run` runs without writing to DB or `.alerts/`
- [ ] Alert `.md` file written to `.alerts/` on WARN/FAIL (our mock data has WARNs, so this fires)
- [ ] `.alerts/latest.md` always reflects the most recent run
- [ ] `python3 scripts/run_scheduler.py --daemon --interval 1` loops and runs every minute (Ctrl-C to stop)
- [ ] `dq_schedule.yaml` exists at project root and controls behaviour
- [ ] `metrica/monitoring/scheduler.py` and `metrica/monitoring/alerting.py` implemented
- [ ] `schedule` library added to `pyproject.toml` dependencies
- [ ] `.alerts/` and `.logs/` added to `.gitignore`
- [ ] All new tests pass
- [ ] All 14 existing tests still pass — zero regressions
- [ ] README updated with scheduler usage section
- [ ] Run `pytest tests/ -v` at the end and confirm

## Technical Notes

- Use only `schedule` as a new dependency — everything else already in `.venv`
- `pip install schedule` in the venv before coding, confirm it works on ARM
- The `--daemon` mode doesn't need to be tested in CI (it runs forever) — test `run_once()` directly
- Keep `metrica/monitoring/scheduler.py` importable without side effects — no code that runs at import time
- The `ScheduleRunResult` model goes in `metrica/monitoring/scheduler.py` alongside `DQScheduler`
- Error handling: if `run_dq_checks()` raises, catch, log to `.logs/dq_errors.log`, and continue (don't crash the daemon)



---
## Agent Response (2026-04-06 02:00:45)
**Outcome**: completed

Scheduled DQ runner complete: DQScheduler with cron (--once) and daemon (--daemon) modes, markdown alerting with latest.md tracking, dry-run support, dq_schedule.yaml config. 7 new tests (21 total, all passing). CLI verified end-to-end.
