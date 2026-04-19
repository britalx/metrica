"""DQ metadata store backed by DuckDB for embedded analytical queries."""

from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dq_runs (
    run_id          VARCHAR PRIMARY KEY,
    target_id       VARCHAR NOT NULL,
    composite_score DOUBLE NOT NULL,
    overall_severity VARCHAR NOT NULL,
    run_started_at  TIMESTAMP NOT NULL,
    run_finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dq_scores (
    id              INTEGER PRIMARY KEY,
    run_id          VARCHAR NOT NULL REFERENCES dq_runs(run_id),
    rule_id         VARCHAR NOT NULL,
    target_id       VARCHAR NOT NULL,
    dimension       VARCHAR NOT NULL,
    score           DOUBLE NOT NULL,
    severity        VARCHAR NOT NULL,
    records_checked INTEGER DEFAULT 0,
    records_failed  INTEGER DEFAULT 0,
    details         VARCHAR DEFAULT '',
    checked_at      TIMESTAMP NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS dq_scores_seq START 1;
"""


class DQStore:
    """Embedded DuckDB store for DQ run results and trend analysis."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self.conn = duckdb.connect(self.db_path)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute(SCHEMA_SQL)

    def record_run(self, run_id: str, target_id: str, composite_score: float,
                   overall_severity: str, started_at, finished_at=None):
        self.conn.execute(
            "INSERT INTO dq_runs VALUES (?, ?, ?, ?, ?, ?)",
            [run_id, target_id, composite_score, overall_severity, started_at, finished_at],
        )

    def record_score(self, run_id: str, rule_id: str, target_id: str,
                     dimension: str, score: float, severity: str,
                     records_checked: int = 0, records_failed: int = 0,
                     details: str = "", checked_at=None):
        seq = self.conn.execute("SELECT nextval('dq_scores_seq')").fetchone()[0]
        self.conn.execute(
            "INSERT INTO dq_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [seq, run_id, rule_id, target_id, dimension, score, severity,
             records_checked, records_failed, details, checked_at],
        )

    def latest_scores(self, target_id: str) -> list[dict]:
        rows = self.conn.execute("""
            SELECT s.rule_id, s.target_id, s.dimension, s.score, s.severity,
                   s.records_checked, s.records_failed, s.details, s.checked_at
            FROM dq_scores s
            JOIN dq_runs r ON s.run_id = r.run_id
            WHERE s.target_id = ?
            ORDER BY r.run_started_at DESC
            LIMIT 20
        """, [target_id]).fetchall()
        columns = ["rule_id", "target_id", "dimension", "score", "severity",
                    "records_checked", "records_failed", "details", "checked_at"]
        return [dict(zip(columns, row)) for row in rows]

    def trend(self, target_id: str, dimension: str | None = None, limit: int = 30) -> list[dict]:
        if dimension:
            query = """
                SELECT r.run_id, r.run_started_at, s.dimension, s.score, s.severity
                FROM dq_runs r JOIN dq_scores s ON r.run_id = s.run_id
                WHERE r.target_id = ? AND s.dimension = ?
            """
            params: list = [target_id, dimension]
            columns = ["run_id", "run_started_at", "dimension", "score", "severity"]
        else:
            query = """
                SELECT r.run_id, r.run_started_at, r.composite_score, r.overall_severity
                FROM dq_runs r
                WHERE r.target_id = ?
            """
            params = [target_id]
            columns = ["run_id", "run_started_at", "composite_score", "overall_severity"]
        query += f" ORDER BY r.run_started_at DESC LIMIT {int(limit)}"
        rows = self.conn.execute(query, params).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def close(self):
        self.conn.close()
