from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from config import CONFIG
except ModuleNotFoundError:
    from config_Version6 import CONFIG


def _load_results(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File risultati non trovato: {path}")

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("Il file risultati è vuoto")

    tolerance_col = "price_tolerance" if "price_tolerance" in df.columns else "price_tolerance_pct"
    required = {tolerance_col, "total_pnl", "profit_factor", "max_drawdown", "trade_count"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"Colonne mancanti nel file risultati: {missing}")

    df = df.copy()
    df["price_tolerance"] = pd.to_numeric(df[tolerance_col], errors="coerce")
    for col in ("total_pnl", "profit_factor", "max_drawdown", "trade_count"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["price_tolerance", "total_pnl", "profit_factor", "max_drawdown", "trade_count"])
    if df.empty:
        raise ValueError("Nessuna riga valida dopo la pulizia dei dati")

    return df


def _build_tolerance_summary(df: pd.DataFrame) -> pd.DataFrame:
    summary = (
        df.groupby("price_tolerance", dropna=False)
        .agg(
            runs=("price_tolerance", "size"),
            total_pnl_mean=("total_pnl", "mean"),
            total_pnl_median=("total_pnl", "median"),
            total_pnl_best=("total_pnl", "max"),
            profit_factor_mean=("profit_factor", "mean"),
            max_drawdown_mean=("max_drawdown", "mean"),
            trade_count_mean=("trade_count", "mean"),
        )
        .reset_index()
    )

    summary = summary.sort_values(
        by=["profit_factor_mean", "total_pnl_mean", "max_drawdown_mean"],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    numeric_cols = [
        "price_tolerance",
        "total_pnl_mean",
        "total_pnl_median",
        "total_pnl_best",
        "profit_factor_mean",
        "max_drawdown_mean",
        "trade_count_mean",
    ]
    summary[numeric_cols] = summary[numeric_cols].round(4)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analisi per tolleranza LVN da grid search round 2")
    parser.add_argument(
        "--results-csv",
        default=os.path.join(CONFIG.runtime.database_dir, "grid_search_round2", "grid_search_results.csv"),
        help="CSV risultati grid search",
    )
    parser.add_argument(
        "--output-csv",
        default=os.path.join(CONFIG.runtime.database_dir, "grid_search_round2", "lvn_tolerance_summary.csv"),
        help="CSV output analisi per tolleranza",
    )
    parser.add_argument("--top-n", type=int, default=10, help="Numero righe da stampare in output")
    args = parser.parse_args()

    results_df = _load_results(args.results_csv)
    summary_df = _build_tolerance_summary(results_df)

    os.makedirs(os.path.dirname(args.output_csv), exist_ok=True)
    summary_df.to_csv(args.output_csv, index=False)

    print("Analisi tolleranza completata")
    print(f"Input: {args.results_csv}")
    print(f"Output: {args.output_csv}")
    print("\nTop risultati per tolleranza:")
    print(summary_df.head(max(args.top_n, 1)).to_string(index=False))


if __name__ == "__main__":
    main()
