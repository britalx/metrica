"""Load reference data YAML definitions into ref_data_core tables.

Usage:
    python scripts/load_ref_data.py [--db path/to/db.duckdb] [--dry-run]

If --db is omitted, uses data/metrica_mock.duckdb.
If --dry-run is set, prints what would be loaded without executing.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import duckdb
import yaml

from metrica.registry.ref_models import (
    CodeSetDefinition,
    CrosswalkDefinition,
    HierarchyDefinition,
    ManyToOneMapping,
    OneToManyMapping,
    OneToOneMapping,
    SystemDefinition,
)

DEFINITIONS_DIR = Path("definitions/reference")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_systems(conn: duckdb.DuckDBPyConnection, dry_run: bool = False) -> int:
    """Load system YAML files into ref_data_core.system."""
    count = 0
    for f in sorted((DEFINITIONS_DIR / "systems").glob("*.yaml")):
        data = yaml.safe_load(f.read_text())
        obj = SystemDefinition(**data)
        if dry_run:
            print(f"  [dry-run] system: {obj.system_code}")
            count += 1
            continue
        conn.execute(
            """
            INSERT INTO ref_data_core.system
                (system_code, name, description, business_domain,
                 classification, lifecycle_status,
                 biz_effective_from, biz_effective_to)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                obj.system_code,
                obj.name,
                obj.description,
                obj.business_domain,
                obj.classification.value,
                obj.lifecycle_status.value,
                str(obj.biz_effective_from),
                str(obj.biz_effective_to),
            ],
        )
        count += 1
    return count


def load_code_sets(conn: duckdb.DuckDBPyConnection, dry_run: bool = False) -> tuple[int, int]:
    """Load code set YAML files into ref_data_core.codeset + codevalue."""
    cs_count = 0
    cv_count = 0
    for f in sorted((DEFINITIONS_DIR / "code_sets").glob("*.yaml")):
        data = yaml.safe_load(f.read_text())
        obj = CodeSetDefinition(**data)
        if dry_run:
            print(f"  [dry-run] codeset: {obj.system_code}.{obj.codeset_code} ({len(obj.values)} values)")
            cs_count += 1
            cv_count += len(obj.values)
            continue
        conn.execute(
            """
            INSERT INTO ref_data_core.codeset
                (system_code, codeset_code, name, description, owner_domain,
                 biz_effective_from, biz_effective_to)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                obj.system_code,
                obj.codeset_code,
                obj.name,
                obj.description,
                obj.owner_domain,
                str(obj.biz_effective_from),
                str(obj.biz_effective_to),
            ],
        )
        cs_count += 1
        for v in obj.values:
            conn.execute(
                """
                INSERT INTO ref_data_core.codevalue
                    (system_code, codeset_code, code, label, description,
                     biz_effective_from, biz_effective_to)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    obj.system_code,
                    obj.codeset_code,
                    v.code,
                    v.label,
                    v.description,
                    str(v.biz_effective_from),
                    str(v.biz_effective_to),
                ],
            )
            cv_count += 1
    return cs_count, cv_count


def load_crosswalks(conn: duckdb.DuckDBPyConnection, dry_run: bool = False) -> tuple[int, int]:
    """Load crosswalk YAML files into ref_data_core.crosswalk + mapping_value."""
    xw_count = 0
    mv_count = 0
    for f in sorted((DEFINITIONS_DIR / "crosswalks").glob("*.yaml")):
        data = yaml.safe_load(f.read_text())
        obj = CrosswalkDefinition(**data)
        if dry_run:
            print(f"  [dry-run] crosswalk: {obj.crosswalk_code} ({obj.mapping_type.value})")
            xw_count += 1
            continue
        conn.execute(
            """
            INSERT INTO ref_data_core.crosswalk
                (source_system, target_system, crosswalk_code, name, description,
                 mapping_type, biz_effective_from, biz_effective_to)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                obj.source_system,
                obj.target_system,
                obj.crosswalk_code,
                obj.name,
                obj.description,
                obj.mapping_type.value,
                str(obj.biz_effective_from),
                str(obj.biz_effective_to),
            ],
        )
        xw_count += 1

        for m in obj.mappings:
            if isinstance(m, OneToOneMapping):
                _insert_mapping(conn, obj, m.source_code, m.target_code, None, False, m)
                mv_count += 1
            elif isinstance(m, ManyToOneMapping):
                for sc in m.source_codes:
                    _insert_mapping(conn, obj, sc, m.target_code, None, False, m)
                    mv_count += 1
            elif isinstance(m, OneToManyMapping):
                for rule in m.routing_rules:
                    target = rule.resolved_target
                    condition = rule.when
                    is_default = rule.default is not None
                    _insert_mapping(conn, obj, m.source_code, target, condition, is_default, m)
                    mv_count += 1
    return xw_count, mv_count


def _insert_mapping(
    conn: duckdb.DuckDBPyConnection,
    xw: CrosswalkDefinition,
    source_code: str,
    target_code: str,
    routing_condition: str | None,
    is_default: bool,
    m: OneToOneMapping | ManyToOneMapping | OneToManyMapping,
) -> None:
    conn.execute(
        """
        INSERT INTO ref_data_core.mapping_value
            (source_system, target_system, crosswalk_code,
             source_code, target_code, routing_condition, is_default,
             biz_effective_from, biz_effective_to)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            xw.source_system,
            xw.target_system,
            xw.crosswalk_code,
            source_code,
            target_code,
            routing_condition,
            is_default,
            str(m.biz_effective_from),
            str(m.biz_effective_to),
        ],
    )


def load_hierarchies(conn: duckdb.DuckDBPyConnection, dry_run: bool = False) -> tuple[int, int]:
    """Load hierarchy YAML files into ref_data_core.hierarchy + hierarchy_value."""
    h_count = 0
    hv_count = 0
    for f in sorted((DEFINITIONS_DIR / "hierarchies").glob("*.yaml")):
        data = yaml.safe_load(f.read_text())
        obj = HierarchyDefinition(**data)
        if dry_run:
            print(f"  [dry-run] hierarchy: {obj.hierarchy_code} ({len(obj.nodes)} nodes)")
            h_count += 1
            hv_count += len(obj.nodes)
            continue
        conn.execute(
            """
            INSERT INTO ref_data_core.hierarchy
                (system_code, hierarchy_code, name, description, levels,
                 biz_effective_from, biz_effective_to)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                obj.system_code,
                obj.hierarchy_code,
                obj.name,
                obj.description,
                json.dumps(obj.levels),
                str(obj.biz_effective_from),
                str(obj.biz_effective_to),
            ],
        )
        h_count += 1
        for n in obj.nodes:
            conn.execute(
                """
                INSERT INTO ref_data_core.hierarchy_value
                    (system_code, hierarchy_code, node_code, label, level,
                     parent_code, biz_effective_from, biz_effective_to)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    obj.system_code,
                    obj.hierarchy_code,
                    n.node_code,
                    n.label,
                    n.level,
                    n.parent_code,
                    str(n.biz_effective_from),
                    str(n.biz_effective_to),
                ],
            )
            hv_count += 1
    return h_count, hv_count


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create ref_data_core and ref_data_semla schemas from DDL files."""
    conn.execute(Path("sql/005_ref_data_core.sql").read_text())
    conn.execute(Path("sql/006_ref_data_semla.sql").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description="Load reference data YAML into DuckDB")
    parser.add_argument("--db", default="data/metrica_mock.duckdb", help="Path to DuckDB file")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be loaded")
    args = parser.parse_args()

    conn = duckdb.connect(args.db)
    print(f"[{_now()}] Connected to {args.db}")

    # Create schemas and tables
    init_schema(conn)
    print(f"[{_now()}] Schema initialized (ref_data_core + ref_data_semla)")

    # Load all entity types
    sys_count = load_systems(conn, args.dry_run)
    print(f"[{_now()}] Systems: {sys_count} loaded")

    cs_count, cv_count = load_code_sets(conn, args.dry_run)
    print(f"[{_now()}] Code sets: {cs_count} sets, {cv_count} values loaded")

    xw_count, mv_count = load_crosswalks(conn, args.dry_run)
    print(f"[{_now()}] Crosswalks: {xw_count} crosswalks, {mv_count} mappings loaded")

    h_count, hv_count = load_hierarchies(conn, args.dry_run)
    print(f"[{_now()}] Hierarchies: {h_count} hierarchies, {hv_count} nodes loaded")

    total = sys_count + cs_count + cv_count + xw_count + mv_count + h_count + hv_count
    print(f"[{_now()}] Done — {total} total records loaded")

    conn.close()


if __name__ == "__main__":
    main()
