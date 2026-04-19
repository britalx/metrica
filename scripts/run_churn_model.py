"""CLI entry point for training and evaluating the Metrica churn model.

Usage:
    python3 scripts/run_churn_model.py --train
    python3 scripts/run_churn_model.py --train --no-gate
    python3 scripts/run_churn_model.py --results
    python3 scripts/run_churn_model.py --importances
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

from metrica.ml.trainer import ChurnModelTrainer

DB_PATH = Path(__file__).parent.parent / "data" / "metrica_mock.duckdb"
DEFINITIONS_ROOT = Path(__file__).parent.parent / "definitions"


def run_training(enforce_gate: bool) -> None:
    trainer = ChurnModelTrainer(DB_PATH, DEFINITIONS_ROOT)

    print("Metrica Churn Model — Baseline Training")
    print("=" * 40)
    print("Building feature matrix...")

    result = trainer.train_baseline(enforce_dq_gate=enforce_gate)

    print(f"  Features in X:      {len(result.features_used)}")
    print(f"  Features gated out: {len(result.features_gated)}")
    print()
    print(f"Dataset: {result.training_customers + result.test_customers} customers "
          f"| {result.churn_rate_train:.1%} churn rate (train)")
    print(f"Split: {result.training_customers} train / {result.test_customers} test (stratified)")
    print()
    print(f"Training LogisticRegression(class_weight='balanced', max_iter=1000)...")
    print()

    ev = result.evaluation
    print("── Evaluation (test set) " + "─" * 36)
    print(f"  AUC-ROC:          {ev.auc_roc:.3f}")
    print(f"  Avg Precision:    {ev.avg_precision:.3f}")
    print(f"  Accuracy:         {ev.accuracy:.3f}")
    print(f"  Precision:        {ev.precision:.3f}  (at threshold {ev.threshold_used:.2f})")
    print(f"  Recall:           {ev.recall:.3f}")
    print(f"  F1 Score:         {ev.f1_score:.3f}")
    print()
    print("Confusion Matrix:")
    print(f"              Predicted 0   Predicted 1")
    print(f"  Actual 0    {ev.true_negatives:>8}      {ev.false_positives:>8}")
    print(f"  Actual 1    {ev.false_negatives:>8}      {ev.true_positives:>8}")
    print()

    print("── Top 10 Feature Importances " + "─" * 30)
    for fi in result.feature_importances[:10]:
        sign = "+" if fi.coefficient >= 0 else ""
        gated_note = "  [GATED]" if fi.metric_id in result.features_gated else ""
        print(f"  {fi.rank:>2}. {fi.metric_id:<30} {sign}{fi.coefficient:.3f}{gated_note}")

    print()
    print(f"Run ID: {result.run_id}")
    print("Persisted to ml.model_runs ✅")


def show_results() -> None:
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = conn.execute(
            "SELECT * FROM ml.model_runs ORDER BY trained_at DESC LIMIT 1"
        ).fetchone()
    except duckdb.CatalogException:
        print("No model runs found. Train a model first with --train")
        return
    finally:
        conn.close()

    if not row:
        print("No model runs found. Train a model first with --train")
        return

    cols = [
        "run_id", "model_type", "trained_at", "training_customers", "test_customers",
        "features_used_json", "features_gated_json", "churn_rate_train", "churn_rate_test",
        "auc_roc", "avg_precision", "accuracy", "precision_score", "recall_score",
        "f1_score", "dq_gate_threshold", "evaluation_json", "importances_json", "notes",
    ]
    data = dict(zip(cols, row))

    print(f"Latest Model Run: {data['run_id']}")
    print("=" * 40)
    print(f"  Model:           {data['model_type']}")
    print(f"  Trained at:      {data['trained_at']}")
    print(f"  Train/Test:      {data['training_customers']}/{data['test_customers']}")
    print(f"  Churn rate:      {data['churn_rate_train']:.1%} train / {data['churn_rate_test']:.1%} test")
    print(f"  AUC-ROC:         {data['auc_roc']:.3f}")
    print(f"  Avg Precision:   {data['avg_precision']:.3f}")
    print(f"  Accuracy:        {data['accuracy']:.3f}")
    print(f"  Precision:       {data['precision_score']:.3f}")
    print(f"  Recall:          {data['recall_score']:.3f}")
    print(f"  F1 Score:        {data['f1_score']:.3f}")
    print(f"  Gate threshold:  {data['dq_gate_threshold']:.2f}")
    print(f"  Features used:   {len(json.loads(data['features_used_json']))}")
    print(f"  Features gated:  {len(json.loads(data['features_gated_json']))}")


def show_importances() -> None:
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        row = conn.execute(
            "SELECT importances_json, features_gated_json FROM ml.model_runs "
            "ORDER BY trained_at DESC LIMIT 1"
        ).fetchone()
    except duckdb.CatalogException:
        print("No model runs found. Train a model first with --train")
        return
    finally:
        conn.close()

    if not row:
        print("No model runs found. Train a model first with --train")
        return

    importances = json.loads(row[0])
    gated = set(json.loads(row[1]))

    print("Feature Importances (by |coefficient|)")
    print("=" * 50)
    for fi in importances:
        sign = "+" if fi["coefficient"] >= 0 else ""
        gated_note = "  [GATED]" if fi["metric_id"] in gated else ""
        print(f"  {fi['rank']:>2}. {fi['metric_id']:<30} {sign}{fi['coefficient']:.4f}{gated_note}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Metrica Churn Model CLI")
    parser.add_argument("--train", action="store_true", help="Train baseline model")
    parser.add_argument("--no-gate", action="store_true", help="Disable DQ gate")
    parser.add_argument("--results", action="store_true", help="Show last model run results")
    parser.add_argument("--importances", action="store_true", help="Show feature importances")

    args = parser.parse_args()

    if not any([args.train, args.results, args.importances]):
        parser.print_help()
        sys.exit(1)

    if args.train:
        run_training(enforce_gate=not args.no_gate)

    if args.results:
        show_results()

    if args.importances:
        show_importances()


if __name__ == "__main__":
    main()
