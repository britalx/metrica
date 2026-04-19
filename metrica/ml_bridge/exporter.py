"""Dataset export utilities for the Feature Store."""

from __future__ import annotations

import csv
from pathlib import Path

from metrica.ml_bridge.models import FeatureMatrix


def export_to_csv(matrix: FeatureMatrix, output_path: Path) -> Path:
    """Write feature matrix to CSV. Returns path written."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not matrix.records:
        output_path.write_text("customer_id\n")
        return output_path

    # Columns: customer_id + all served metrics
    columns = ["customer_id"] + matrix.metrics_served

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for record in matrix.records:
            row = [record.customer_id]
            for mid in matrix.metrics_served:
                row.append(record.features.get(mid, ""))
            writer.writerow(row)

    return output_path


def export_to_parquet(matrix: FeatureMatrix, output_path: Path) -> Path:
    """Write feature matrix to Parquet if pyarrow is available."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise ImportError(
            "pyarrow is required for Parquet export. "
            "Install it with: pip install pyarrow"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    columns = ["customer_id"] + matrix.metrics_served
    data = {col: [] for col in columns}

    for record in matrix.records:
        data["customer_id"].append(record.customer_id)
        for mid in matrix.metrics_served:
            data[mid].append(record.features.get(mid))

    table = pa.table(data)
    pq.write_table(table, str(output_path))
    return output_path


def export_summary(matrix: FeatureMatrix) -> str:
    """Return a human-readable summary string of the matrix."""
    lines = [
        "Metrica Feature Matrix Summary",
        "=" * 40,
        f"Customers:       {matrix.total_customers}",
        f"Total metrics:   {matrix.total_metrics}",
        f"Metrics served:  {len(matrix.metrics_served)}",
        f"Metrics gated:   {len(matrix.metrics_gated)}",
        f"Gate threshold:  {matrix.gate_threshold:.2f}",
        f"Assembled at:    {matrix.assembled_at.isoformat()}",
    ]

    if matrix.metrics_gated:
        lines.append("")
        lines.append("Gated metrics:")
        for mid in matrix.metrics_gated:
            lines.append(f"  - {mid}")

    if matrix.metrics_served:
        lines.append("")
        lines.append(f"Served metrics ({len(matrix.metrics_served)}):")
        for mid in matrix.metrics_served[:10]:
            lines.append(f"  + {mid}")
        if len(matrix.metrics_served) > 10:
            lines.append(f"  ... and {len(matrix.metrics_served) - 10} more")

    return "\n".join(lines)
