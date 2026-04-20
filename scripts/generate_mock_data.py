"""Mock data generator for Metrica pilot metrics.

Generates realistic telecom customer data with intentional DQ issues
for testing the DQ pipeline end-to-end.

Usage:
    python3 scripts/generate_mock_data.py
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

# Reproducible randomness
random.seed(42)

NUM_CUSTOMERS = 1000
DB_PATH = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"

# Imperfection: percentage of churners that have "good" profiles
# (simulating competitor poaching, not service dissatisfaction)
IMPERFECTION_PCT = 0.15  # 15% of churners will have contradictory data


def generate_customer_id(i: int) -> str:
    return f"CUST-{i:04d}"


def random_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def create_schemas(conn: duckdb.DuckDBPyConnection):
    conn.execute("CREATE SCHEMA IF NOT EXISTS raw")
    conn.execute("CREATE SCHEMA IF NOT EXISTS metrics")
    conn.execute("CREATE SCHEMA IF NOT EXISTS dq")


def generate_crm_customers(conn: duckdb.DuckDBPyConnection):
    """Generate raw.crm_customers — 1,000 customers with DQ issues injected.

    pmd_flag (Perfect Mock Data): TRUE for customers with clean correlated data,
    FALSE for imperfect/contradictory data (e.g., churners with good profiles).
    """
    conn.execute("""
        CREATE OR REPLACE TABLE raw.crm_customers (
            customer_id     VARCHAR PRIMARY KEY,
            activation_date DATE,
            account_status  VARCHAR,
            contract_type   VARCHAR,
            reactivation_date DATE,
            churn_label_30d INTEGER,
            pmd_flag        BOOLEAN DEFAULT TRUE
        )
    """)

    rows = []
    for i in range(1, NUM_CUSTOMERS + 1):
        cid = generate_customer_id(i)

        # Account status: 90% active, 5% suspended, 5% terminated
        r = random.random()
        if r < 0.90:
            status = "active"
        elif r < 0.95:
            status = "suspended"
        else:
            status = "terminated"

        # Contract type: 40% month_to_month, 35% one_year, 25% two_year
        r = random.random()
        if r < 0.40:
            contract = "month_to_month"
        elif r < 0.75:
            contract = "one_year"
        else:
            contract = "two_year"

        # Activation date: 2015-01-01 to 2024-12-01
        activation = random_date(date(2015, 1, 1), date(2024, 12, 1))

        # Reactivation: NULL for 95%, random date > activation for 5%
        reactivation = None
        if random.random() < 0.05:
            reactivation = random_date(activation + timedelta(days=30), date(2025, 12, 1))

        # churn_label_30d: 1 if account_status == 'terminated' else 0
        # In production, churn would be derived from status transitions with a 30-day window.
        churn_label = 1 if status == "terminated" else 0

        rows.append((cid, activation, status, contract, reactivation, churn_label, True))

    # Identify churner indices for imperfection injection
    churner_indices = [i for i, r in enumerate(rows) if r[5] == 1]
    num_imperfect = max(1, int(len(churner_indices) * IMPERFECTION_PCT))
    imperfect_churners = set(random.sample(churner_indices, min(num_imperfect, len(churner_indices))))

    # Mark imperfect churners with pmd_flag=False and give them longer tenure (good profile)
    for idx in imperfect_churners:
        r = rows[idx]
        # Give them an older activation date (long tenure = looks loyal)
        good_activation = random_date(date(2015, 1, 1), date(2018, 6, 1))
        rows[idx] = (r[0], good_activation, r[2], "two_year", r[4], r[5], False)

    # DQ ISSUE: inject 50 null activation_dates (5% completeness issue)
    null_indices = random.sample(range(len(rows)), 50)
    for idx in null_indices:
        r = rows[idx]
        rows[idx] = (r[0], None, r[2], r[3], r[4], r[5], r[6])

    # DQ ISSUE: inject 10 future activation_dates (1% accuracy issue)
    future_indices = random.sample(
        [i for i in range(len(rows)) if rows[i][1] is not None], 10
    )
    for idx in future_indices:
        r = rows[idx]
        rows[idx] = (r[0], date(2027, 1, 1), r[2], r[3], r[4], r[5], r[6])

    conn.executemany(
        "INSERT INTO raw.crm_customers VALUES (?, ?, ?, ?, ?, ?, ?)", rows
    )
    num_imperfect_total = sum(1 for r in rows if not r[6])
    print(f"  raw.crm_customers: {len(rows)} rows (50 null dates, 10 future dates, {num_imperfect_total} imperfect churners)")

    # Return imperfect churner IDs for downstream generators
    return {r[0] for r in rows if not r[6]}


def generate_billing_invoices(conn: duckdb.DuckDBPyConnection, imperfect_ids: set[str]):
    """Generate raw.billing_invoices — latest invoice per customer with DQ issues."""
    conn.execute("""
        CREATE OR REPLACE TABLE raw.billing_invoices (
            invoice_id            VARCHAR PRIMARY KEY,
            customer_id           VARCHAR,
            invoice_date          DATE,
            monthly_charge_amount DOUBLE,
            base_plan_charge      DOUBLE,
            add_on_charges        DOUBLE
        )
    """)

    rows = []
    for i in range(1, NUM_CUSTOMERS + 1):
        cid = generate_customer_id(i)
        inv_id = f"INV-{i:06d}"

        # Invoice date: between 2026-02-01 and 2026-03-31
        inv_date = random_date(date(2026, 2, 1), date(2026, 3, 31))

        # Imperfect churners get moderate charges (not high = looks like happy customer)
        if cid in imperfect_ids:
            charge = max(30.0, min(80.0, random.gauss(50, 10)))
        else:
            # Monthly charge: normal distribution, mean=65, std=25, clamped [15, 300]
            charge = max(15.0, min(300.0, random.gauss(65, 25)))
        charge = round(charge, 2)
        base = round(charge * 0.80, 2)
        addon = round(charge - base, 2)

        rows.append((inv_id, cid, inv_date, charge, base, addon))

    # DQ ISSUE: inject 20 negative charges (2% validity issue)
    neg_indices = random.sample(range(len(rows)), 20)
    for idx in neg_indices:
        r = rows[idx]
        rows[idx] = (r[0], r[1], r[2], -5.0, -4.0, -1.0)

    # DQ ISSUE: inject 30 stale invoice dates (3% timeliness issue)
    stale_indices = random.sample(range(len(rows)), 30)
    for idx in stale_indices:
        r = rows[idx]
        stale_date = date(2026, 1, 1)  # ~60+ days ago from "current"
        rows[idx] = (r[0], r[1], stale_date, r[3], r[4], r[5])

    conn.executemany(
        "INSERT INTO raw.billing_invoices VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    print(f"  raw.billing_invoices: {len(rows)} rows (20 negative charges, 30 stale dates)")


def generate_contact_center(conn: duckdb.DuckDBPyConnection, imperfect_ids: set[str]):
    """Generate raw.contact_center_interactions with DQ issues."""
    conn.execute("""
        CREATE OR REPLACE TABLE raw.contact_center_interactions (
            interaction_id    VARCHAR,
            customer_id       VARCHAR,
            interaction_date  DATE,
            interaction_type  VARCHAR,
            channel           VARCHAR,
            resolution_status VARCHAR
        )
    """)

    rows = []
    interaction_counter = 0
    today = date(2026, 3, 15)  # Reference "today" for consistency

    for i in range(1, NUM_CUSTOMERS + 1):
        cid = generate_customer_id(i)
        is_imperfect = cid in imperfect_ids

        # Imperfect churners get active-customer distribution (few support calls)
        # Distribution for total interactions (last 60 days):
        # 60% = 0 calls, 25% = 1-2, 10% = 3-5, 5% = 6+
        r = random.random()
        if is_imperfect:
            # Active-like: mostly 0 interactions
            if r < 0.70:
                num_interactions = 0
            elif r < 0.90:
                num_interactions = random.randint(1, 2)
            else:
                num_interactions = random.randint(3, 4)
        elif r < 0.60:
            num_interactions = 0
        elif r < 0.85:
            num_interactions = random.randint(1, 3)
        elif r < 0.95:
            num_interactions = random.randint(4, 7)
        else:
            num_interactions = random.randint(8, 15)

        for _ in range(num_interactions):
            interaction_counter += 1
            int_id = f"INT-{interaction_counter:07d}"
            int_date = random_date(today - timedelta(days=60), today)

            # Type: 70% call, 20% chat, 10% email
            r2 = random.random()
            if r2 < 0.70:
                int_type = "call"
            elif r2 < 0.90:
                int_type = "chat"
            else:
                int_type = "email"

            # Resolution: 75% resolved, 15% pending, 10% escalated
            r3 = random.random()
            if r3 < 0.75:
                resolution = "resolved"
            elif r3 < 0.90:
                resolution = "pending"
            else:
                resolution = "escalated"

            rows.append((int_id, cid, int_date, int_type, int_type, resolution))

    # DQ ISSUE: inject 20 duplicate interaction_id rows (consistency issue)
    if len(rows) >= 20:
        dup_indices = random.sample(range(len(rows)), 20)
        for idx in dup_indices:
            # Duplicate the row with same interaction_id
            rows.append(rows[idx])

    conn.executemany(
        "INSERT INTO raw.contact_center_interactions VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    print(f"  raw.contact_center_interactions: {len(rows)} rows (20 duplicate IDs)")


def generate_cdr_records(conn: duckdb.DuckDBPyConnection):
    """Generate raw.cdr_call_records — ~55K CDR rows with churn correlation.

    Uses pure SQL generation for performance on ARM.
    """
    conn.execute("""
        CREATE OR REPLACE TABLE raw.cdr_call_records (
            record_id        VARCHAR,
            customer_id      VARCHAR,
            call_date        DATE,
            call_type        VARCHAR,
            duration_seconds INTEGER,
            data_bytes       BIGINT,
            is_roaming       BOOLEAN,
            is_dropped       BOOLEAN,
            is_night         BOOLEAN,
            is_weekend       BOOLEAN
        )
    """)

    conn.execute("SELECT setseed(0.42)")
    conn.execute("""
        INSERT INTO raw.cdr_call_records
        WITH customers AS (
            SELECT customer_id,
                   CASE WHEN account_status = 'terminated' AND pmd_flag = TRUE THEN 1 ELSE 0 END AS is_churned
            FROM raw.crm_customers
        ),
        expanded AS (
            SELECT c.customer_id, c.is_churned,
                   generate_series AS seq
            FROM customers c,
                 generate_series(1,
                     CASE WHEN c.is_churned = 1 THEN 15 + CAST(abs(hash(c.customer_id || 'n')) % 21 AS BIGINT)
                          ELSE 40 + CAST(abs(hash(c.customer_id || 'n')) % 41 AS BIGINT)
                     END)
        ),
        records AS (
            SELECT
                'CDR-' || LPAD(CAST(ROW_NUMBER() OVER () AS VARCHAR), 8, '0') AS record_id,
                e.customer_id,
                DATE '2025-12-15' + INTERVAL (abs(hash(e.customer_id || CAST(e.seq AS VARCHAR) || 'd')) % 91) DAY AS call_date,
                CASE WHEN random() < 0.60 THEN 'voice'
                     WHEN random() < 0.85 THEN 'data'
                     ELSE 'sms' END AS call_type,
                e.is_churned,
                random() AS r1, random() AS r2, random() AS r3, random() AS r4
            FROM expanded e
        )
        SELECT
            record_id,
            customer_id,
            CAST(call_date AS DATE) AS call_date,
            call_type,
            -- duration
            CASE WHEN call_type = 'voice' THEN
                     GREATEST(5, CAST(
                         CASE WHEN is_churned = 1 THEN 120 + r1 * 120 - 60
                              ELSE 240 + r1 * 180 - 90 END AS INTEGER))
                 WHEN call_type = 'data' THEN
                     GREATEST(10, CAST(
                         CASE WHEN is_churned = 1 THEN 300 + r1 * 300 - 150
                              ELSE 600 + r1 * 400 - 200 END AS INTEGER))
                 ELSE 0 END AS duration_seconds,
            -- data_bytes
            CASE WHEN call_type = 'data' THEN
                     GREATEST(1000, CAST(
                         CASE WHEN is_churned = 1 THEN 5000000 + r2 * 6000000 - 3000000
                              ELSE 20000000 + r2 * 20000000 - 10000000 END AS BIGINT))
                 ELSE 0 END AS data_bytes,
            -- is_roaming
            r3 < CASE WHEN is_churned = 1 THEN 0.03 ELSE 0.08 END AS is_roaming,
            -- is_dropped (voice only)
            call_type = 'voice' AND r4 < CASE WHEN is_churned = 1 THEN 0.15 ELSE 0.03 END AS is_dropped,
            -- is_night
            random() < 0.25 AS is_night,
            -- is_weekend
            DAYOFWEEK(CAST(call_date AS DATE)) IN (0, 6) AS is_weekend
        FROM records
    """)

    count = conn.execute("SELECT COUNT(*) FROM raw.cdr_call_records").fetchone()[0]
    churned = conn.execute("""
        SELECT COUNT(DISTINCT c.customer_id)
        FROM raw.cdr_call_records c
        JOIN raw.crm_customers cu ON c.customer_id = cu.customer_id
        WHERE cu.account_status = 'terminated'
    """).fetchone()[0]
    print(f"  raw.cdr_call_records: {count} rows ({churned} churned customers)")


def generate_network_measurements(conn: duckdb.DuckDBPyConnection):
    """Generate raw.network_measurements — ~31K rows with churn correlation.

    Uses pure SQL generation for performance on ARM.
    """
    conn.execute("""
        CREATE OR REPLACE TABLE raw.network_measurements (
            measurement_id  VARCHAR,
            customer_id     VARCHAR,
            measured_at     DATE,
            cell_id         VARCHAR,
            rsrp_dbm        FLOAT,
            speed_mbps      FLOAT,
            outage_flag     BOOLEAN,
            throttle_flag   BOOLEAN
        )
    """)

    conn.execute("SELECT setseed(0.43)")
    conn.execute("""
        INSERT INTO raw.network_measurements
        WITH customers AS (
            SELECT customer_id,
                   CASE WHEN account_status = 'terminated' AND pmd_flag = TRUE THEN 1 ELSE 0 END AS is_churned,
                   'CELL-' || LPAD(CAST(1 + abs(hash(customer_id || 'cell')) % 100 AS VARCHAR), 3, '0') AS cell_id
            FROM raw.crm_customers
        ),
        days AS (
            SELECT CAST(generate_series AS INTEGER) AS day_offset
            FROM generate_series(0, 90, 3)
        ),
        expanded AS (
            SELECT c.customer_id, c.is_churned, c.cell_id,
                   DATE '2025-12-15' + INTERVAL (d.day_offset) DAY AS meas_date
            FROM customers c CROSS JOIN days d
        )
        SELECT
            'NET-' || LPAD(CAST(ROW_NUMBER() OVER () AS VARCHAR), 8, '0') AS measurement_id,
            customer_id,
            CAST(meas_date AS DATE) AS measured_at,
            cell_id,
            -- rsrp: churned = weak (-105 ± 12), active = good (-85 ± 10)
            GREATEST(-140.0, LEAST(-44.0, ROUND(
                CASE WHEN is_churned = 1 THEN -105 + (random() + random() + random() - 1.5) * 12
                     ELSE -85 + (random() + random() + random() - 1.5) * 10
                END, 1))) AS rsrp_dbm,
            -- speed correlated with signal (computed in next step)
            0.0 AS speed_mbps,
            -- outage: churned 3x more likely
            random() < CASE WHEN is_churned = 1 THEN 0.06 ELSE 0.02 END AS outage_flag,
            -- throttle
            random() < CASE WHEN is_churned = 1 THEN 0.10 ELSE 0.03 END AS throttle_flag
        FROM expanded
    """)

    # Update speed based on rsrp (correlated)
    conn.execute("SELECT setseed(0.44)")
    conn.execute("""
        UPDATE raw.network_measurements
        SET speed_mbps = GREATEST(0.5, LEAST(200.0,
            ROUND((rsrp_dbm + 140) * 0.8 + (random() - 0.5) * 10, 1)))
    """)

    count = conn.execute("SELECT COUNT(*) FROM raw.network_measurements").fetchone()[0]
    churned = conn.execute("""
        SELECT COUNT(DISTINCT n.customer_id)
        FROM raw.network_measurements n
        JOIN raw.crm_customers cu ON n.customer_id = cu.customer_id
        WHERE cu.account_status = 'terminated'
    """).fetchone()[0]
    print(f"  raw.network_measurements: {count} rows ({churned} churned customers)")


def generate_app_events(conn: duckdb.DuckDBPyConnection):
    """Generate raw.app_events — ~15K rows with churn correlation.

    Uses pure SQL generation for performance on ARM.
    """
    conn.execute("""
        CREATE OR REPLACE TABLE raw.app_events (
            event_id      VARCHAR,
            customer_id   VARCHAR,
            event_date    DATE,
            event_type    VARCHAR,
            event_detail  VARCHAR
        )
    """)

    conn.execute("SELECT setseed(0.45)")
    conn.execute("""
        INSERT INTO raw.app_events
        WITH customers AS (
            SELECT customer_id,
                   CASE WHEN account_status = 'terminated' AND pmd_flag = TRUE THEN 1 ELSE 0 END AS is_churned
            FROM raw.crm_customers
        ),
        expanded AS (
            SELECT c.customer_id, c.is_churned,
                   generate_series AS seq
            FROM customers c,
                 generate_series(1,
                     CASE WHEN c.is_churned = 1 THEN CAST(abs(hash(c.customer_id || 'app')) % 6 AS BIGINT)
                          ELSE 8 + CAST(abs(hash(c.customer_id || 'app')) % 23 AS BIGINT)
                     END)
        ),
        records AS (
            SELECT
                'APP-' || LPAD(CAST(ROW_NUMBER() OVER () AS VARCHAR), 8, '0') AS event_id,
                e.customer_id,
                -- Churned: events cluster in first 30 days; Active: spread across 60 days
                CASE WHEN e.is_churned = 1
                     THEN DATE '2026-01-14' + INTERVAL (abs(hash(e.customer_id || CAST(e.seq AS VARCHAR) || 'ed')) % 31) DAY
                     ELSE DATE '2026-01-14' + INTERVAL (abs(hash(e.customer_id || CAST(e.seq AS VARCHAR) || 'ed')) % 61) DAY
                END AS event_date,
                e.is_churned,
                random() AS r1
            FROM expanded e
        )
        SELECT
            event_id,
            customer_id,
            CAST(event_date AS DATE) AS event_date,
            -- Event type: churned = fewer logins, more support; active = mostly logins
            CASE WHEN is_churned = 1 THEN
                     CASE WHEN r1 < 0.30 THEN 'login'
                          WHEN r1 < 0.50 THEN 'chat_support'
                          WHEN r1 < 0.70 THEN 'view_bill'
                          WHEN r1 < 0.85 THEN 'view_usage'
                          ELSE 'change_plan' END
                 ELSE
                     CASE WHEN r1 < 0.55 THEN 'login'
                          WHEN r1 < 0.70 THEN 'view_usage'
                          WHEN r1 < 0.85 THEN 'view_bill'
                          WHEN r1 < 0.95 THEN 'chat_support'
                          ELSE 'change_plan' END
            END AS event_type,
            CASE WHEN is_churned = 1 THEN
                     CASE WHEN r1 < 0.30 THEN 'login'
                          WHEN r1 < 0.50 THEN 'chat_support'
                          WHEN r1 < 0.70 THEN 'view_bill'
                          WHEN r1 < 0.85 THEN 'view_usage'
                          ELSE 'change_plan' END
                 ELSE
                     CASE WHEN r1 < 0.55 THEN 'login'
                          WHEN r1 < 0.70 THEN 'view_usage'
                          WHEN r1 < 0.85 THEN 'view_bill'
                          WHEN r1 < 0.95 THEN 'chat_support'
                          ELSE 'change_plan' END
            END || '_session' AS event_detail
        FROM records
    """)

    count = conn.execute("SELECT COUNT(*) FROM raw.app_events").fetchone()[0]
    churned = conn.execute("""
        SELECT COUNT(DISTINCT a.customer_id)
        FROM raw.app_events a
        JOIN raw.crm_customers cu ON a.customer_id = cu.customer_id
        WHERE cu.account_status = 'terminated'
    """).fetchone()[0]
    print(f"  raw.app_events: {count} rows ({churned} churned customers)")


def compute_metrics(conn: duckdb.DuckDBPyConnection):
    """Compute metrics.customer_metrics from source tables."""
    conn.execute("""
        CREATE OR REPLACE TABLE metrics.customer_metrics (
            customer_id       VARCHAR PRIMARY KEY,
            tenure_months     INTEGER,
            monthly_charges   DOUBLE,
            support_calls_30d INTEGER,
            churn_label_30d   INTEGER,
            late_payment_flag INTEGER,
            avg_monthly_minutes    FLOAT,
            calls_per_day          FLOAT,
            data_usage_gb          FLOAT,
            sms_count              INTEGER,
            roaming_usage          FLOAT,
            night_weekend_usage_ratio FLOAT,
            usage_trend_3m         FLOAT,
            dropped_call_rate      FLOAT,
            avg_signal_strength_home FLOAT,
            outage_events_experienced INTEGER,
            data_throttling_events INTEGER,
            speed_test_avg_mbps    FLOAT,
            login_app_frequency    FLOAT,
            days_since_last_login  INTEGER,
            usage_vs_plan_utilization FLOAT,
            last_updated      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        INSERT INTO metrics.customer_metrics (
            customer_id, tenure_months, monthly_charges, support_calls_30d,
            churn_label_30d, avg_monthly_minutes, calls_per_day, data_usage_gb,
            sms_count, roaming_usage, night_weekend_usage_ratio, usage_trend_3m,
            dropped_call_rate, avg_signal_strength_home, outage_events_experienced,
            data_throttling_events, speed_test_avg_mbps, login_app_frequency,
            days_since_last_login, usage_vs_plan_utilization
        )
        SELECT
            c.customer_id,
            -- tenure
            CASE WHEN c.activation_date IS NULL THEN NULL
                 ELSE CAST(DATEDIFF('month', c.activation_date, DATE '2026-03-15') AS INTEGER)
            END AS tenure_months,
            -- billing
            b.monthly_charge_amount AS monthly_charges,
            COALESCE(cc.call_count, 0) AS support_calls_30d,
            -- churn label
            c.churn_label_30d,
            -- CDR metrics
            cdr_agg.avg_monthly_minutes,
            cdr_agg.calls_per_day,
            cdr_agg.data_usage_gb,
            cdr_agg.sms_count,
            cdr_agg.roaming_usage,
            cdr_agg.night_weekend_usage_ratio,
            cdr_agg.usage_trend_3m,
            cdr_agg.dropped_call_rate,
            -- network metrics
            net_agg.avg_signal_strength_home,
            net_agg.outage_events_experienced,
            net_agg.data_throttling_events,
            net_agg.speed_test_avg_mbps,
            -- app metrics
            app_agg.login_app_frequency,
            app_agg.days_since_last_login,
            COALESCE(cdr_agg.data_usage_gb / 5.0, 0) AS usage_vs_plan_utilization
        FROM raw.crm_customers c
        LEFT JOIN raw.billing_invoices b ON c.customer_id = b.customer_id
        LEFT JOIN (
            SELECT customer_id, COUNT(*) AS call_count
            FROM raw.contact_center_interactions
            WHERE interaction_type = 'call'
              AND interaction_date >= DATE '2026-02-13'
            GROUP BY customer_id
        ) cc ON c.customer_id = cc.customer_id
        LEFT JOIN (
            SELECT
                customer_id,
                AVG(monthly_mins) AS avg_monthly_minutes,
                SUM(CASE WHEN call_date >= DATE '2026-02-13' THEN 1 ELSE 0 END)::FLOAT / 30.0
                    AS calls_per_day,
                SUM(data_bytes)::FLOAT / (1024*1024*1024) AS data_usage_gb,
                SUM(CASE WHEN call_type = 'sms' THEN 1 ELSE 0 END) AS sms_count,
                SUM(CASE WHEN is_roaming AND call_type = 'voice'
                         THEN duration_seconds / 60.0 ELSE 0 END) AS roaming_usage,
                SUM(CASE WHEN is_night OR is_weekend THEN 1 ELSE 0 END)::FLOAT
                    / NULLIF(COUNT(*), 0) AS night_weekend_usage_ratio,
                (SUM(CASE WHEN call_date >= DATE '2026-02-13'
                          THEN duration_seconds ELSE 0 END)::FLOAT
                 - SUM(CASE WHEN call_date < DATE '2026-02-13'
                            AND call_date >= DATE '2026-01-14'
                            THEN duration_seconds ELSE 0 END)::FLOAT)
                / NULLIF(SUM(CASE WHEN call_date < DATE '2026-02-13'
                                  AND call_date >= DATE '2026-01-14'
                                  THEN duration_seconds ELSE 0 END)::FLOAT, 0)
                    AS usage_trend_3m,
                SUM(CASE WHEN is_dropped AND call_date >= DATE '2026-02-13'
                         THEN 1 ELSE 0 END)::FLOAT
                / NULLIF(SUM(CASE WHEN call_date >= DATE '2026-02-13'
                              THEN 1 ELSE 0 END)::FLOAT, 0) AS dropped_call_rate
            FROM (
                SELECT *,
                    SUM(CASE WHEN call_type='voice' THEN duration_seconds/60.0 ELSE 0 END)
                        OVER (PARTITION BY customer_id,
                              DATE_TRUNC('month', call_date)) AS monthly_mins
                FROM raw.cdr_call_records
                WHERE call_date >= DATE '2025-12-15'
            ) sub
            GROUP BY customer_id
        ) cdr_agg ON c.customer_id = cdr_agg.customer_id
        LEFT JOIN (
            SELECT
                customer_id,
                AVG(rsrp_dbm) AS avg_signal_strength_home,
                SUM(CASE WHEN outage_flag THEN 1 ELSE 0 END) AS outage_events_experienced,
                SUM(CASE WHEN throttle_flag AND measured_at >= DATE '2026-02-13'
                         THEN 1 ELSE 0 END) AS data_throttling_events,
                AVG(speed_mbps) AS speed_test_avg_mbps
            FROM raw.network_measurements
            GROUP BY customer_id
        ) net_agg ON c.customer_id = net_agg.customer_id
        LEFT JOIN (
            SELECT
                customer_id,
                COUNT(CASE WHEN event_type = 'login' THEN 1 END)::FLOAT / 4.3
                    AS login_app_frequency,
                CAST(DATEDIFF('day',
                    MAX(CASE WHEN event_type = 'login' THEN event_date END),
                    DATE '2026-03-15') AS INTEGER) AS days_since_last_login
            FROM raw.app_events
            GROUP BY customer_id
        ) app_agg ON c.customer_id = app_agg.customer_id
    """)

    # Populate late_payment_flag with correlated mock labels.
    # Correlations per user story:
    #   - low tenure, high overage, month_to_month contracts, infrequent app logins.
    # Plus ~10% "imperfect" defaulters (long-tenure customers who still default — life events).
    # Target base rate: 8-12%.
    conn.execute("SELECT setseed(0.47)")
    conn.execute("""
        WITH signals AS (
            SELECT
                m.customer_id,
                m.tenure_months,
                m.monthly_charges,
                m.login_app_frequency,
                c.contract_type,
                -- Low tenure score: 0..1 where shorter tenure = higher risk
                CASE
                    WHEN m.tenure_months IS NULL THEN 0.5
                    WHEN m.tenure_months < 12 THEN 0.9
                    WHEN m.tenure_months < 24 THEN 0.6
                    WHEN m.tenure_months < 60 THEN 0.3
                    ELSE 0.1
                END AS tenure_risk,
                -- High monthly charges proxy for overage risk (no discrete overage field in mock data)
                CASE
                    WHEN m.monthly_charges IS NULL THEN 0.3
                    WHEN m.monthly_charges > 120 THEN 0.8
                    WHEN m.monthly_charges > 80 THEN 0.5
                    WHEN m.monthly_charges > 50 THEN 0.3
                    ELSE 0.15
                END AS overage_risk,
                CASE c.contract_type
                    WHEN 'month_to_month' THEN 0.7
                    WHEN 'one_year' THEN 0.3
                    WHEN 'two_year' THEN 0.15
                    ELSE 0.4
                END AS contract_risk,
                -- Low app-login frequency = higher risk
                CASE
                    WHEN m.login_app_frequency IS NULL THEN 0.5
                    WHEN m.login_app_frequency < 0.5 THEN 0.8
                    WHEN m.login_app_frequency < 2.0 THEN 0.5
                    WHEN m.login_app_frequency < 5.0 THEN 0.3
                    ELSE 0.15
                END AS login_risk
            FROM metrics.customer_metrics m
            LEFT JOIN raw.crm_customers c USING (customer_id)
        ),
        scored AS (
            SELECT
                customer_id,
                (0.30 * tenure_risk
                 + 0.30 * overage_risk
                 + 0.25 * contract_risk
                 + 0.15 * login_risk) AS risk_score
            FROM signals
        )
        UPDATE metrics.customer_metrics AS m
        SET late_payment_flag = CASE
            -- High risk: substantial chance of default
            WHEN s.risk_score > 0.50 AND random() < 0.60 THEN 1
            -- Mid risk: moderate chance
            WHEN s.risk_score > 0.35 AND random() < 0.15 THEN 1
            -- Low risk: small background rate
            WHEN s.risk_score <= 0.35 AND random() < 0.04 THEN 1
            ELSE 0
        END
        FROM scored s
        WHERE m.customer_id = s.customer_id
    """)

    # Inject "imperfect" defaulters: long-tenure customers flipped to late_payment=1.
    # These represent life events (hospitalization, job loss) that correlated features can't predict.
    # Target ~10% of total defaulters to be "imperfect" per the user story.
    conn.execute("""
        UPDATE metrics.customer_metrics
        SET late_payment_flag = 1
        WHERE customer_id IN (
            SELECT customer_id FROM metrics.customer_metrics
            WHERE late_payment_flag = 0
              AND tenure_months >= 60
            USING SAMPLE 2%
        )
    """)

    count = conn.execute("SELECT COUNT(*) FROM metrics.customer_metrics").fetchone()[0]
    late_count = conn.execute(
        "SELECT COUNT(*) FROM metrics.customer_metrics WHERE late_payment_flag = 1"
    ).fetchone()[0]
    late_rate = late_count / count if count else 0.0
    print(f"  metrics.customer_metrics: {count} rows computed "
          f"(late_payment_flag rate: {late_rate:.1%})")


def create_dq_tables(conn: duckdb.DuckDBPyConnection):
    """Create DQ metadata tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dq.dq_runs (
            run_id          VARCHAR PRIMARY KEY,
            target_id       VARCHAR NOT NULL,
            composite_score DOUBLE NOT NULL,
            overall_severity VARCHAR NOT NULL,
            run_started_at  TIMESTAMP NOT NULL,
            run_finished_at TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dq.dq_scores (
            id              INTEGER PRIMARY KEY,
            run_id          VARCHAR NOT NULL,
            rule_id         VARCHAR NOT NULL,
            target_id       VARCHAR NOT NULL,
            dimension       VARCHAR NOT NULL,
            score           DOUBLE NOT NULL,
            severity        VARCHAR NOT NULL,
            records_checked INTEGER DEFAULT 0,
            records_failed  INTEGER DEFAULT 0,
            details         VARCHAR DEFAULT '',
            checked_at      TIMESTAMP NOT NULL
        )
    """)
    conn.execute("CREATE SEQUENCE IF NOT EXISTS dq_scores_seq START 1")
    print("  dq.dq_runs + dq.dq_scores tables created")


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing DB to start fresh
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = duckdb.connect(str(DB_PATH))
    print(f"Generating mock data -> {DB_PATH}")

    create_schemas(conn)
    imperfect_ids = generate_crm_customers(conn)
    generate_billing_invoices(conn, imperfect_ids)
    generate_contact_center(conn, imperfect_ids)
    generate_cdr_records(conn)
    generate_network_measurements(conn)
    generate_app_events(conn)
    compute_metrics(conn)
    create_dq_tables(conn)

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
