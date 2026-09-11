from __future__ import annotations

import argparse
import importlib
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd


def _load_config_module():
    try:
        return importlib.import_module("config")
    except ModuleNotFoundError:
        cfg_mod = importlib.import_module("config_Version6")
        sys.modules.setdefault("config", cfg_mod)
        return cfg_mod


def _load_engine_module():
    try:
        return importlib.import_module("engine")
    except ModuleNotFoundError:
        return importlib.import_module("engine_Version2")


_config_module = _load_config_module()
CONFIG = _config_module.CONFIG
ENGINE = _load_engine_module()


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


def _classify_signal(prev_close: float, last_close: float, lvn: float) -> str:
    if hasattr(ENGINE, "_classify_signal"):
        return ENGINE._classify_signal(prev_close, last_close, lvn)

    if abs(last_close - lvn) > CONFIG.strategy.price_tolerance:
        return "WAIT"
    if prev_close > lvn:
        return "LONG"
    if prev_close < lvn:
        return "SHORT"
    return "WAIT"


def _signal_for_index(df: pd.DataFrame, idx: int) -> Tuple[str, Optional[float], str]:
    if idx < CONFIG.strategy.window_profile:
        return "WAIT", None, "Insufficient profile window"

    analysis_window = df.iloc[idx - CONFIG.strategy.window_profile:idx].copy()
    last_row = df.iloc[idx]
    prev_row = df.iloc[idx - 1]

    last_close = float(last_row["Close"])
    prev_close = float(prev_row["Close"])

    lvns = ENGINE.get_lvn_nodes(analysis_window)
    if not lvns:
        return "WAIT", None, "No valid LVN detected"

    for lvn in lvns:
        if abs(last_close - lvn) <= CONFIG.strategy.price_tolerance:
            signal = _classify_signal(prev_close, last_close, lvn)
            return signal, round(float(lvn), 3), f"Price touched LVN {round(float(lvn), 3)}"

    return "WAIT", None, "No touch on LVN"


def _open_position(ticker: str, signal: str, date_str: str, price: float) -> Optional[PositionState]:
    if signal not in {"LONG", "SHORT"} or price <= 0:
        return None

    quantity = int(CONFIG.strategy.investimento_per_trade / price)
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


def _close_trade(position: PositionState, exit_date: str, exit_price: float, exit_reason: str) -> Dict:
    pnl_move = (
        (exit_price - position.entry_price) * position.quantity
        if position.direction == "LONG"
        else (position.entry_price - exit_price) * position.quantity
    )
    realized_pnl = position.pnl_euro + pnl_move - float(CONFIG.strategy.commissione_chiusura)
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


def _update_position(position: PositionState, date_str: str, current_price: float) -> Optional[Dict]:
    if position.entry_price <= 0 or position.quantity <= 0:
        return None

    rendimento = (
        (current_price - position.entry_price) / position.entry_price
        if position.direction == "LONG"
        else (position.entry_price - current_price) / position.entry_price
    )

    if not position.tp1_hit and rendimento >= 0.04:
        half_qty = position.quantity // 2 or position.quantity
        closed_pnl = (
            (current_price - position.entry_price) * half_qty
            if position.direction == "LONG"
            else (position.entry_price - current_price) * half_qty
        )

        position.pnl_euro = position.pnl_euro + closed_pnl - float(CONFIG.strategy.commissione_chiusura)
        position.quantity -= half_qty
        position.tp1_hit = True
        position.current_stop = (
            current_price * 0.98 if position.direction == "LONG" else current_price * 1.02
        )

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
                "return_pct": round((float(position.pnl_euro) / position.invested_amount) * 100, 4)
                if position.invested_amount
                else 0.0,
                "exit_reason": "TP1 full close",
            }

    elif position.tp1_hit:
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
            return _close_trade(position, date_str, current_price, "Trailing stop exit")

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


def _build_summaries(trades_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if trades_df.empty:
        ticker_summary = pd.DataFrame(
            columns=[
                "ticker",
                "trade_count",
                "win_rate",
                "total_pnl",
                "avg_pnl_per_trade",
                "profit_factor",
                "max_drawdown",
            ]
        )
        global_summary = pd.DataFrame(
            [
                {
                    "total_trades": 0,
                    "total_pnl": 0.0,
                    "overall_win_rate": 0.0,
                    "profit_factor": 0.0,
                    "max_drawdown": 0.0,
                }
            ]
        )
        return ticker_summary, global_summary

    rows = []
    for ticker, grp in trades_df.groupby("ticker", sort=True):
        count = int(len(grp))
        wins = int((grp["realized_pnl"] > 0).sum())
        rows.append(
            {
                "ticker": ticker,
                "trade_count": count,
                "win_rate": round((wins / count) * 100, 2) if count else 0.0,
                "total_pnl": round(float(grp["realized_pnl"].sum()), 2),
                "avg_pnl_per_trade": round(float(grp["realized_pnl"].mean()), 2) if count else 0.0,
                "profit_factor": _profit_factor(grp["realized_pnl"]),
                "max_drawdown": _max_drawdown(grp),
            }
        )

    summary_by_ticker = pd.DataFrame(rows).sort_values("total_pnl", ascending=False).reset_index(drop=True)

    total_trades = int(len(trades_df))
    total_wins = int((trades_df["realized_pnl"] > 0).sum())
    summary_global = pd.DataFrame(
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

    return summary_by_ticker, summary_global


def run_backtest(data_dir: str, output_dir: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    os.makedirs(output_dir, exist_ok=True)

    trades: List[Dict] = []

    for file_name in sorted(os.listdir(data_dir)):
        if not file_name.endswith(".csv"):
            continue

        ticker = file_name.replace(".csv", "")
        file_path = os.path.join(data_dir, file_name)
        df = _safe_read_csv(file_path)

        if df is None or len(df) < CONFIG.strategy.window_profile + 1:
            continue

        position: Optional[PositionState] = None

        for idx in range(CONFIG.strategy.window_profile, len(df)):
            row = df.iloc[idx]
            date_str = str(pd.to_datetime(row["Date"]).date())
            close_price = float(row["Close"])

            signal, _, _ = _signal_for_index(df, idx)

            if position is not None:
                closed_trade = _update_position(position, date_str, close_price)
                if closed_trade is not None:
                    trades.append(closed_trade)
                    position = None

            if position is None and signal in {"LONG", "SHORT"}:
                position = _open_position(ticker, signal, date_str, close_price)

        if position is not None:
            last_row = df.iloc[-1]
            last_date = str(pd.to_datetime(last_row["Date"]).date())
            last_price = float(last_row["Close"])
            trades.append(_close_trade(position, last_date, last_price, "End of data"))

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

    summary_by_ticker_df, summary_global_df = _build_summaries(trades_df)

    trades_df.to_csv(os.path.join(output_dir, "trades.csv"), index=False)
    summary_by_ticker_df.to_csv(os.path.join(output_dir, "summary_by_ticker.csv"), index=False)
    summary_global_df.to_csv(os.path.join(output_dir, "summary_global.csv"), index=False)

    return trades_df, summary_by_ticker_df, summary_global_df


def main() -> None:
    parser = argparse.ArgumentParser(description="LVN Sentinel backtest su dati CSV storici")
    parser.add_argument("--data-dir", default=CONFIG.runtime.data_dir, help="Directory con CSV storici")
    parser.add_argument(
        "--output-dir",
        default=os.path.join(CONFIG.runtime.database_dir, "backtest"),
        help="Directory output risultati",
    )

    args = parser.parse_args()

    if not os.path.isdir(args.data_dir):
        raise FileNotFoundError(f"Data directory non trovata: {args.data_dir}")

    trades_df, summary_by_ticker_df, summary_global_df = run_backtest(args.data_dir, args.output_dir)

    print("Backtest completato")
    print(f"Trades: {len(trades_df)}")
    print(f"Ticker analizzati con trade: {len(summary_by_ticker_df)}")
    print(f"Output salvati in: {args.output_dir}")


if __name__ == "__main__":
    main()
