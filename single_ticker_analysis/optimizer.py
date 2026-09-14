from __future__ import annotations

import argparse
import itertools
import os
from dataclasses import asdict
from typing import Dict, List

import pandas as pd

from backtest import build_summaries, run_backtest_for_ticker
from config import CONFIG
from engine import StrategyParams


def _parse_int_list(raw: str) -> List[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _parse_float_list(raw: str) -> List[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def _discover_tickers(data_dir: str) -> List[str]:
    if not os.path.isdir(data_dir):
        return []
    return sorted([f.replace(".csv", "") for f in os.listdir(data_dir) if f.endswith(".csv") and f != "failed_tickers.csv"])


def _run_global_with_shared_params(data_dir: str, tickers: List[str], params: StrategyParams) -> pd.DataFrame:
    all_trades: List[pd.DataFrame] = []
    for ticker in tickers:
        trades = run_backtest_for_ticker(
            data_dir=data_dir,
            ticker=ticker,
            params=params,
            investimento_per_trade=CONFIG.strategy.investimento_per_trade,
            commissione_apertura=CONFIG.strategy.commissione_apertura,
            commissione_chiusura=CONFIG.strategy.commissione_chiusura,
        )
        if not trades.empty:
            all_trades.append(trades)
    if not all_trades:
        return pd.DataFrame(columns=["ticker", "direction", "entry_date", "exit_date", "entry_price", "exit_price", "quantity", "realized_pnl", "return_pct", "exit_reason"])
    return pd.concat(all_trades, ignore_index=True)


def _save_baseline(output_dir: str, params: StrategyParams, trades_df: pd.DataFrame) -> pd.DataFrame:
    baseline_dir = os.path.join(output_dir, "baseline_global")
    os.makedirs(baseline_dir, exist_ok=True)
    summary_by_ticker_df, summary_global_df = build_summaries(trades_df)
    trades_df.to_csv(os.path.join(baseline_dir, "trades.csv"), index=False)
    summary_by_ticker_df.to_csv(os.path.join(baseline_dir, "summary_by_ticker.csv"), index=False)
    summary_global_df.to_csv(os.path.join(baseline_dir, "summary_global.csv"), index=False)
    pd.DataFrame([asdict(params)]).to_csv(os.path.join(baseline_dir, "params.csv"), index=False)
    return summary_global_df


def _score_ticker_combos(data_dir: str, ticker: str, combos: List[tuple]) -> pd.DataFrame:
    rows: List[Dict] = []
    for window_profile, price_tolerance, lvn_threshold in combos:
        params = StrategyParams(
            window_profile=window_profile,
            price_tolerance=price_tolerance,
            lvn_threshold=lvn_threshold,
            bin_step=CONFIG.strategy.bin_step,
            min_profile_levels=CONFIG.strategy.min_profile_levels,
            rsi_period=CONFIG.strategy.rsi_period,
            rsi_long_max=CONFIG.strategy.rsi_long_max,
            rsi_short_min=CONFIG.strategy.rsi_short_min,
        )
        trades_df = run_backtest_for_ticker(
            data_dir=data_dir,
            ticker=ticker,
            params=params,
            investimento_per_trade=CONFIG.strategy.investimento_per_trade,
            commissione_apertura=CONFIG.strategy.commissione_apertura,
            commissione_chiusura=CONFIG.strategy.commissione_chiusura,
        )
        _, summary_global_df = build_summaries(trades_df)
        metrics = summary_global_df.iloc[0].to_dict()
        metrics.update(
            {
                "ticker": ticker,
                "window_profile": window_profile,
                "price_tolerance": price_tolerance,
                "lvn_threshold": lvn_threshold,
                "trade_count": len(trades_df),
            }
        )
        rows.append(metrics)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Single ticker optimizer + baseline comparison")
    parser.add_argument("--data-dir", default=CONFIG.runtime.data_dir)
    parser.add_argument("--output-dir", default=CONFIG.runtime.output_dir)
    parser.add_argument("--tickers", nargs="*", default=None)
    parser.add_argument("--window-profiles", default=",".join(map(str, CONFIG.grid.window_profiles)))
    parser.add_argument("--price-tolerances", default=",".join(map(str, CONFIG.grid.price_tolerances)))
    parser.add_argument("--lvn-thresholds", default=",".join(map(str, CONFIG.grid.lvn_thresholds)))
    parser.add_argument("--top-n", type=int, default=CONFIG.grid.top_n)
    args = parser.parse_args()

    tickers = args.tickers if args.tickers else _discover_tickers(args.data_dir)
    if not tickers:
        raise ValueError(f"Nessun ticker CSV trovato in {args.data_dir}")

    os.makedirs(args.output_dir, exist_ok=True)
    combos = list(
        itertools.product(
            _parse_int_list(args.window_profiles),
            _parse_float_list(args.price_tolerances),
            _parse_float_list(args.lvn_thresholds),
        )
    )
    if not combos:
        raise ValueError("Nessuna combinazione parametri disponibile")

    baseline_params = StrategyParams(
        window_profile=CONFIG.strategy.window_profile,
        price_tolerance=CONFIG.strategy.price_tolerance,
        lvn_threshold=CONFIG.strategy.lvn_threshold,
        bin_step=CONFIG.strategy.bin_step,
        min_profile_levels=CONFIG.strategy.min_profile_levels,
        rsi_period=CONFIG.strategy.rsi_period,
        rsi_long_max=CONFIG.strategy.rsi_long_max,
        rsi_short_min=CONFIG.strategy.rsi_short_min,
    )
    baseline_trades = _run_global_with_shared_params(args.data_dir, tickers, baseline_params)
    baseline_global_df = _save_baseline(args.output_dir, baseline_params, baseline_trades)

    per_ticker_root = os.path.join(args.output_dir, "per_ticker")
    os.makedirs(per_ticker_root, exist_ok=True)

    best_params_rows: List[Dict] = []
    best_trades_frames: List[pd.DataFrame] = []

    for ticker in tickers:
        ticker_results = _score_ticker_combos(args.data_dir, ticker, combos)
        ticker_results = ticker_results.sort_values(
            by=["profit_factor", "total_pnl", "max_drawdown", "trade_count"],
            ascending=[False, False, True, False],
        ).reset_index(drop=True)

        ticker_dir = os.path.join(per_ticker_root, ticker)
        os.makedirs(ticker_dir, exist_ok=True)
        ticker_results.to_csv(os.path.join(ticker_dir, "results.csv"), index=False)
        ticker_results.head(max(args.top_n, 1)).to_csv(os.path.join(ticker_dir, "ranking.csv"), index=False)

        best = ticker_results.iloc[0].to_dict()
        pd.DataFrame([best]).to_csv(os.path.join(ticker_dir, "best_params.csv"), index=False)
        best_params_rows.append(best)

        best_params = StrategyParams(
            window_profile=int(best["window_profile"]),
            price_tolerance=float(best["price_tolerance"]),
            lvn_threshold=float(best["lvn_threshold"]),
            bin_step=CONFIG.strategy.bin_step,
            min_profile_levels=CONFIG.strategy.min_profile_levels,
            rsi_period=CONFIG.strategy.rsi_period,
            rsi_long_max=CONFIG.strategy.rsi_long_max,
            rsi_short_min=CONFIG.strategy.rsi_short_min,
        )
        best_trades = run_backtest_for_ticker(
            data_dir=args.data_dir,
            ticker=ticker,
            params=best_params,
            investimento_per_trade=CONFIG.strategy.investimento_per_trade,
            commissione_apertura=CONFIG.strategy.commissione_apertura,
            commissione_chiusura=CONFIG.strategy.commissione_chiusura,
        )
        if not best_trades.empty:
            best_trades_frames.append(best_trades)

    best_global_dir = os.path.join(args.output_dir, "per_ticker_best_global")
    os.makedirs(best_global_dir, exist_ok=True)
    best_params_df = pd.DataFrame(best_params_rows)
    best_params_df.to_csv(os.path.join(best_global_dir, "best_params_all_tickers.csv"), index=False)

    if best_trades_frames:
        per_ticker_best_trades = pd.concat(best_trades_frames, ignore_index=True)
    else:
        per_ticker_best_trades = pd.DataFrame(columns=["ticker", "direction", "entry_date", "exit_date", "entry_price", "exit_price", "quantity", "realized_pnl", "return_pct", "exit_reason"])
    per_ticker_best_trades.to_csv(os.path.join(best_global_dir, "trades.csv"), index=False)
    per_ticker_summary_by_ticker, per_ticker_summary_global = build_summaries(per_ticker_best_trades)
    per_ticker_summary_by_ticker.to_csv(os.path.join(best_global_dir, "summary_by_ticker.csv"), index=False)
    per_ticker_summary_global.to_csv(os.path.join(best_global_dir, "summary_global.csv"), index=False)

    baseline_row = baseline_global_df.iloc[0]
    optimized_row = per_ticker_summary_global.iloc[0]
    comparison = pd.DataFrame(
        [
            {
                "scenario": "baseline_global",
                "total_trades": baseline_row["total_trades"],
                "total_pnl": baseline_row["total_pnl"],
                "overall_win_rate": baseline_row["overall_win_rate"],
                "profit_factor": baseline_row["profit_factor"],
                "max_drawdown": baseline_row["max_drawdown"],
            },
            {
                "scenario": "per_ticker_best_global",
                "total_trades": optimized_row["total_trades"],
                "total_pnl": optimized_row["total_pnl"],
                "overall_win_rate": optimized_row["overall_win_rate"],
                "profit_factor": optimized_row["profit_factor"],
                "max_drawdown": optimized_row["max_drawdown"],
            },
            {
                "scenario": "delta_optimized_minus_baseline",
                "total_trades": float(optimized_row["total_trades"]) - float(baseline_row["total_trades"]),
                "total_pnl": float(optimized_row["total_pnl"]) - float(baseline_row["total_pnl"]),
                "overall_win_rate": float(optimized_row["overall_win_rate"]) - float(baseline_row["overall_win_rate"]),
                "profit_factor": float(optimized_row["profit_factor"]) - float(baseline_row["profit_factor"]),
                "max_drawdown": float(optimized_row["max_drawdown"]) - float(baseline_row["max_drawdown"]),
            },
        ]
    )
    comparison.to_csv(os.path.join(args.output_dir, "comparison_baseline_vs_per_ticker.csv"), index=False)
    print(f"Ottimizzazione completata. Output: {args.output_dir}")


if __name__ == "__main__":
    main()

