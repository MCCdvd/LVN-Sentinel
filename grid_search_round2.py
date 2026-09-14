from __future__ import annotations

import argparse
import itertools
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from config import CONFIG
except ModuleNotFoundError:
    from config_Version6 import CONFIG


DEFAULT_TICKERS = [
    "BAYN",
    "PUM",
    "DSY",
    "CS",
    "ITM",
    "MONC",
    "BFF",
    "ENGI",
    "EOAN",
    "FBK",
    "MB",
    "STLAM",
    "BMPS",
    "PST",
    "BAMI",
    "AZM",
    "ENEL",
    "NEXI",
    "HFG",
    "TIT",
    "TEN",
    "UCG",
    "URW",
    "SPM",
]


@dataclass
class PositionState:
    ticker: str
    direction: str
    entry_date: str
    entry_price: float
    quantity: int
    initial_quantity: int
    invested_amount: float
    pnl_euro: float
    tp1_hit: bool = False
    current_stop: float = 0.0


def _safe_read_csv(file_path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(file_path):
        return None

    try:
        df = pd.read_csv(file_path)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    required = {"Date", "Close", "Volume"}
    if not required.issubset(df.columns):
        return None

    work = df.copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work["Close"] = pd.to_numeric(work["Close"], errors="coerce")
    work["Volume"] = pd.to_numeric(work["Volume"], errors="coerce")
    work = work.dropna(subset=["Date", "Close", "Volume"]).sort_values("Date").reset_index(drop=True)

    if work.empty:
        return None

    return work


def _build_volume_profile(df_window: pd.DataFrame, step: float) -> pd.Series:
    work = df_window.copy()
    work["PriceBin"] = (work["Close"] / step).round() * step
    profile = work.groupby("PriceBin")["Volume"].sum().sort_index()
    return profile


def get_lvn_nodes(df_window: pd.DataFrame, bin_step: float, lvn_threshold: float, min_profile_levels: int) -> List[float]:
    profile = _build_volume_profile(df_window, bin_step)

    if profile is None or len(profile) < min_profile_levels:
        return []

    values = profile.values
    if np.all(values == 0):
        return []

    poc_volume = float(profile.max())
    candidate_idx = np.array([], dtype=int)

    if len(profile) >= 7:
        candidate_idx = argrelextrema(values, np.less, order=2)[0]

    lvns = []
    for idx in candidate_idx:
        price_level = float(profile.index[idx])
        level_volume = float(profile.iloc[idx])
        if level_volume < poc_volume * lvn_threshold:
            lvns.append(round(price_level, 3))

    return sorted(list(set(lvns)))


def _calculate_rsi(closes: pd.Series, period: int) -> Optional[float]:
    if closes is None or len(closes) < period + 1:
        return None

    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    last_avg_gain = avg_gain.iloc[-1]
    last_avg_loss = avg_loss.iloc[-1]

    if pd.isna(last_avg_gain) or pd.isna(last_avg_loss):
        return None

    if last_avg_loss == 0:
        return 100.0

    rs = last_avg_gain / last_avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi), 2)


def _apply_rsi_filter(signal: str, rsi_value: Optional[float], rsi_long_max: float, rsi_short_min: float) -> str:
    if signal == "LONG":
        if rsi_value is None or rsi_value > rsi_long_max:
            return "WAIT"
    elif signal == "SHORT":
        if rsi_value is None or rsi_value < rsi_short_min:
            return "WAIT"
    return signal


def _classify_signal(prev_close: float, last_close: float, lvn: float, price_tolerance: float) -> str:
    if abs(last_close - lvn) > price_tolerance:
        return "WAIT"

    if prev_close > lvn:
        return "LONG"
    if prev_close < lvn:
        return "SHORT"

    return "WAIT"


def _signal_for_index(
    df: pd.DataFrame,
    idx: int,
    window_profile: int,
    price_tolerance: float,
    bin_step: float,
    lvn_threshold: float,
    min_profile_levels: int,
    rsi_period: int,
    rsi_long_max: float,
    rsi_short_min: float,
) -> Tuple[str, Optional[float], str, Optional[float]]:
    if idx < window_profile:
        return "WAIT", None, "Insufficient profile window", None

    analysis_window = df.iloc[idx - window_profile:idx].copy()
    last_row = df.iloc[idx]
    prev_row = df.iloc[idx - 1]

    last_close = float(last_row["Close"])
    prev_close = float(prev_row["Close"])
    rsi_value = _calculate_rsi(df["Close"].iloc[: idx + 1], rsi_period)

    lvns = get_lvn_nodes(analysis_window, bin_step, lvn_threshold, min_profile_levels)
    if not lvns:
        return "WAIT", None, "No valid LVN detected", rsi_value

    for lvn in lvns:
        if abs(last_close - lvn) <= price_tolerance:
            signal = _classify_signal(prev_close, last_close, lvn, price_tolerance)
            signal = _apply_rsi_filter(signal, rsi_value, rsi_long_max, rsi_short_min)
            reason = f"Price touched LVN {round(float(lvn), 3)}"
            if signal == "WAIT":
                reason = f"Price touched LVN {round(float(lvn), 3)}, filter blocked entry"
            return signal, round(float(lvn), 3), reason, rsi_value

    return "WAIT", None, "No touch on LVN", rsi_value


def _open_position(ticker: str, signal: str, date_str: str, price: float, investment: float) -> Optional[PositionState]:
    if signal not in {"LONG", "SHORT"} or price <= 0:
        return None

    quantity = int(investment / price)
    if quantity <= 0:
        return None

    invested_amount = round(quantity * price, 2)
    return PositionState(
        ticker=ticker,
        direction=signal,
        entry_date=date_str,
        entry_price=float(price),
        quantity=quantity,
        initial_quantity=quantity,
        invested_amount=invested_amount,
        pnl_euro=-float(CONFIG.strategy.commissione_apertura),
    )


def _close_trade(position: PositionState, exit_date: str, exit_price: float, exit_reason: str, commission_close: float) -> Dict:
    pnl_move = (
        (exit_price - position.entry_price) * position.quantity
        if position.direction == "LONG"
        else (position.entry_price - exit_price) * position.quantity
    )
    realized_pnl = position.pnl_euro + pnl_move - float(commission_close)
    return {
        "ticker": position.ticker,
        "direction": position.direction,
        "entry_date": position.entry_date,
        "exit_date": exit_date,
        "entry_price": round(position.entry_price, 4),
        "exit_price": round(float(exit_price), 4),
        "quantity": int(position.initial_quantity),
        "realized_pnl": round(float(realized_pnl), 2),
        "return_pct": round((float(realized_pnl) / position.invested_amount) * 100, 4) if position.invested_amount else 0.0,
        "exit_reason": exit_reason,
    }


def _update_position(position: PositionState, df: pd.DataFrame, idx: int, date_str: str, current_price: float, params: dict) -> Optional[Dict]:
    if position.entry_price <= 0 or position.quantity <= 0:
        return None

    signal, _, _, _ = _signal_for_index(df, idx, **params)

    if not position.tp1_hit:
        hard_stop_pct = 0.03
        if position.direction == "LONG":
            hard_stop_price = position.entry_price * (1 - hard_stop_pct)
            if current_price <= hard_stop_price:
                return _close_trade(position, date_str, current_price, "Hard stop exit", CONFIG.strategy.commissione_chiusura)
        else:
            hard_stop_price = position.entry_price * (1 + hard_stop_pct)
            if current_price >= hard_stop_price:
                return _close_trade(position, date_str, current_price, "Hard stop exit", CONFIG.strategy.commissione_chiusura)

        opposite_signal = "SHORT" if position.direction == "LONG" else "LONG"
        if signal == opposite_signal:
            half_qty = position.quantity // 2 or position.quantity
            closed_pnl = (
                (current_price - position.entry_price) * half_qty
                if position.direction == "LONG"
                else (position.entry_price - current_price) * half_qty
            )

            position.pnl_euro = position.pnl_euro + closed_pnl - float(CONFIG.strategy.commissione_chiusura)
            position.quantity -= half_qty
            position.tp1_hit = True
            position.current_stop = current_price * 0.98 if position.direction == "LONG" else current_price * 1.02

            if position.quantity <= 0:
                return {
                    "ticker": position.ticker,
                    "direction": position.direction,
                    "entry_date": position.entry_date,
                    "exit_date": date_str,
                    "entry_price": round(position.entry_price, 4),
                    "exit_price": round(float(current_price), 4),
                    "quantity": int(position.initial_quantity),
                    "realized_pnl": round(float(position.pnl_euro), 2),
                    "return_pct": round((float(position.pnl_euro) / position.invested_amount) * 100, 4) if position.invested_amount else 0.0,
                    "exit_reason": "Opposite LVN TP1 full close",
                }

    else:
        is_exit = False

        if position.direction == "LONG":
            new_stop = current_price * 0.98
            if new_stop > position.current_stop:
                position.current_stop = new_stop
            if current_price <= position.current_stop:
                is_exit = True
        else:
            new_stop = current_price * 1.02
            if position.current_stop == 0.0 or new_stop < position.current_stop:
                position.current_stop = new_stop
            if current_price >= position.current_stop:
                is_exit = True

        if is_exit:
            return _close_trade(position, date_str, current_price, "Trailing stop exit", CONFIG.strategy.commissione_chiusura)

    return None


def _profit_factor(pnls: pd.Series) -> float:
    gross_profit = float(pnls[pnls > 0].sum())
    gross_loss = float(pnls[pnls < 0].sum())

    if gross_loss < 0:
        return round(gross_profit / abs(gross_loss), 4)
    if gross_profit > 0:
        return float("inf")
    return 0.0


def _max_drawdown(trades_df: pd.DataFrame) -> float:
    if trades_df.empty:
        return 0.0

    ordered = trades_df.copy()
    ordered["exit_date"] = pd.to_datetime(ordered["exit_date"], errors="coerce")
    ordered = ordered.dropna(subset=["exit_date"]).sort_values("exit_date")
    if ordered.empty:
        return 0.0

    equity = ordered["realized_pnl"].cumsum()
    equity = pd.concat([pd.Series([0.0]), equity], ignore_index=True)
    peak = equity.cummax()
    drawdown = equity - peak
    return round(abs(float(drawdown.min())), 2)


def run_backtest(
    data_dir: str,
    tickers: List[str],
    window_profile: int,
    price_tolerance: float,
    lvn_threshold: float,
    output_dir: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    os.makedirs(output_dir, exist_ok=True)

    trades: List[Dict] = []
    params = dict(
        window_profile=window_profile,
        price_tolerance=price_tolerance,
        bin_step=CONFIG.strategy.bin_step,
        lvn_threshold=lvn_threshold,
        min_profile_levels=CONFIG.strategy.min_profile_levels,
        rsi_period=CONFIG.strategy.rsi_period,
        rsi_long_max=CONFIG.strategy.rsi_long_max,
        rsi_short_min=CONFIG.strategy.rsi_short_min,
    )

    for ticker in tickers:
        file_path = os.path.join(data_dir, f"{ticker}.csv")
        df = _safe_read_csv(file_path)

        if df is None or len(df) < window_profile + 1:
            continue

        position: Optional[PositionState] = None

        for idx in range(window_profile, len(df)):
            row = df.iloc[idx]
            date_str = str(pd.to_datetime(row["Date"]).date())
            close_price = float(row["Close"])

            signal, _, _, _ = _signal_for_index(
                df,
                idx,
                window_profile,
                price_tolerance,
                CONFIG.strategy.bin_step,
                lvn_threshold,
                CONFIG.strategy.min_profile_levels,
                CONFIG.strategy.rsi_period,
                CONFIG.strategy.rsi_long_max,
                CONFIG.strategy.rsi_short_min,
            )

            if position is not None:
                closed_trade = _update_position(position, df, idx, date_str, close_price, params)
                if closed_trade is not None:
                    trades.append(closed_trade)
                    position = None

            if position is None and signal in {"LONG", "SHORT"}:
                position = _open_position(ticker, signal, date_str, close_price, CONFIG.strategy.investimento_per_trade)

        if position is not None:
            last_row = df.iloc[-1]
            last_date = str(pd.to_datetime(last_row["Date"]).date())
            last_price = float(last_row["Close"])
            trades.append(_close_trade(position, last_date, last_price, "End of data", CONFIG.strategy.commissione_chiusura))

    trades_df = pd.DataFrame(
        trades,
        columns=[
            "ticker",
            "direction",
            "entry_date",
            "exit_date",
            "entry_price",
            "exit_price",
            "quantity",
            "realized_pnl",
            "return_pct",
            "exit_reason",
        ],
    )

    if trades_df.empty:
        summary_global_df = pd.DataFrame(
            [{"total_trades": 0, "total_pnl": 0.0, "overall_win_rate": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0}]
        )
    else:
        total_trades = int(len(trades_df))
        total_wins = int((trades_df["realized_pnl"] > 0).sum())
        summary_global_df = pd.DataFrame(
            [
                {
                    "total_trades": total_trades,
                    "total_pnl": round(float(trades_df["realized_pnl"].sum()), 2),
                    "overall_win_rate": round((total_wins / total_trades) * 100, 2) if total_trades else 0.0,
                    "profit_factor": _profit_factor(trades_df["realized_pnl"]),
                    "max_drawdown": _max_drawdown(trades_df),
                }
            ]
        )

    trades_df.to_csv(os.path.join(output_dir, "trades.csv"), index=False)
    summary_global_df.to_csv(os.path.join(output_dir, "summary_global.csv"), index=False)

    return trades_df, summary_global_df


def _parse_float_list(value: str) -> List[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def _parse_int_list(value: str) -> List[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Second round grid search for LVN strategy")
    parser.add_argument("--data-dir", default=CONFIG.runtime.data_dir, help="Directory with CSV ticker files")
    parser.add_argument("--output-dir", default=os.path.join(CONFIG.runtime.database_dir, "grid_search_round2"), help="Output directory")
    parser.add_argument("--tickers", nargs="*", default=DEFAULT_TICKERS, help="Ticker list to test")
    parser.add_argument("--window-profiles", default="12,15,18,20", help="Comma-separated window profile values")
    parser.add_argument("--price-tolerance-pcts", default="0.15,0.18,0.20,0.22,0.25", help="Comma-separated absolute tolerance values")
    parser.add_argument("--lvn-thresholds", default="0.25,0.30,0.35,0.40", help="Comma-separated LVN threshold values")
    parser.add_argument("--top-n", type=int, default=20, help="How many top results to export in ranking")
    args = parser.parse_args()

    window_profiles = _parse_int_list(args.window_profiles)
    price_tolerance_values = _parse_float_list(args.price_tolerance_pcts)
    lvn_thresholds = _parse_float_list(args.lvn_thresholds)

    os.makedirs(args.output_dir, exist_ok=True)

    results: List[Dict] = []
    combos = list(itertools.product(window_profiles, price_tolerance_values, lvn_thresholds))
    total = len(combos)

    for i, (window_profile, price_tolerance, lvn_threshold) in enumerate(combos, start=1):
        run_dir = os.path.join(
            args.output_dir,
            f"wp{window_profile}_pt{str(price_tolerance).replace('.', 'p')}_lvn{str(lvn_threshold).replace('.', 'p')}",
        )
        trades_df, summary_global_df = run_backtest(
            data_dir=args.data_dir,
            tickers=args.tickers,
            window_profile=window_profile,
            price_tolerance=price_tolerance,
            lvn_threshold=lvn_threshold,
            output_dir=run_dir,
        )

        metrics = summary_global_df.iloc[0].to_dict()
        metrics.update(
            {
                "window_profile": window_profile,
                "price_tolerance": price_tolerance,
                "lvn_threshold": lvn_threshold,
                "trade_count": len(trades_df),
                "run_dir": run_dir,
            }
        )
        results.append(metrics)
        print(
            f"[{i}/{total}] wp={window_profile} pt={price_tolerance} lvn={lvn_threshold} -> pnl={metrics['total_pnl']} pf={metrics['profit_factor']}"
        )

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values(
        by=["profit_factor", "total_pnl", "max_drawdown", "trade_count"],
        ascending=[False, False, True, False],
    ).reset_index(drop=True)

    results_csv = os.path.join(args.output_dir, "grid_search_results.csv")
    ranking_csv = os.path.join(args.output_dir, "grid_search_ranking.csv")
    results_df.to_csv(results_csv, index=False)
    results_df.head(args.top_n).to_csv(ranking_csv, index=False)

    print("\nGrid search completata")
    print(f"Risultati completi: {results_csv}")
    print(f"Ranking top {args.top_n}: {ranking_csv}")
    print("\nTop 10 combinazioni:")
    print(results_df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
