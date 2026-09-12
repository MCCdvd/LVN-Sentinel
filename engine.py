import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

from config import CONFIG

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    ticker: str
    date: str
    price: float
    lvn: Optional[float]
    signal: str
    reason: str = ""


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
        logger.exception("Errore lettura file %s", file_path)
        return None

    if df is None or df.empty:
        return None

    required = {"Date", "Close", "Volume"}
    if not required.issubset(df.columns):
        logger.warning("CSV incompleto o non valido: %s", file_path)
        return None

    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df = df.dropna(subset=["Date", "Close", "Volume"]).sort_values("Date").reset_index(drop=True)

    if df.empty:
        return None

    return df


def _build_volume_profile(df_window: pd.DataFrame, step: float = None) -> pd.Series:
    if step is None:
        step = CONFIG.strategy.bin_step

    work = df_window.copy()
    work["PriceBin"] = (work["Close"] / step).round() * step
    profile = work.groupby("PriceBin")["Volume"].sum().sort_index()
    return profile


def get_lvn_nodes(df_window: pd.DataFrame) -> List[float]:
    profile = _build_volume_profile(df_window)

    if profile is None or len(profile) < CONFIG.strategy.min_profile_levels:
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

        if level_volume < poc_volume * CONFIG.strategy.lvn_threshold:
            lvns.append(round(price_level, 3))

    return sorted(list(set(lvns)))


def _classify_signal(prev_close: float, last_close: float, lvn: float) -> str:
    if abs(last_close - lvn) > CONFIG.strategy.price_tolerance:
        return "WAIT"

    if prev_close > lvn:
        return "LONG"
    if prev_close < lvn:
        return "SHORT"

    return "WAIT"


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


def _apply_rsi_filter(signal: str, rsi_value: Optional[float]) -> str:
    if signal == "LONG":
        if rsi_value is None or rsi_value > CONFIG.strategy.rsi_long_max:
            return "WAIT"
    elif signal == "SHORT":
        if rsi_value is None or rsi_value < CONFIG.strategy.rsi_short_min:
            return "WAIT"
    return signal


def analyze_ticker(ticker_name: str) -> Optional[Dict]:
    file_path = os.path.join(CONFIG.runtime.data_dir, f"{ticker_name}.csv")
    df = _safe_read_csv(file_path)

    if df is None or len(df) < CONFIG.strategy.window_profile + 1:
        return None

    analysis_window = df.iloc[-(CONFIG.strategy.window_profile + 1):-1].copy()

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    last_close = float(last_row["Close"])
    prev_close = float(prev_row["Close"])
    last_date = last_row["Date"]

    lvns = get_lvn_nodes(analysis_window)

    if not lvns:
        return {
            "ticker": ticker_name,
            "date": str(last_date.date()),
            "price": round(last_close, 3),
            "lvn": None,
            "rsi": _calculate_rsi(df["Close"], CONFIG.strategy.rsi_period),
            "signal": "WAIT",
            "reason": "No valid LVN detected",
        }

    target_lvn = None
    signal = "WAIT"
    reason = "No touch on LVN"
    rsi_value = _calculate_rsi(df["Close"], CONFIG.strategy.rsi_period)

    for lvn in lvns:
        if abs(last_close - lvn) <= CONFIG.strategy.price_tolerance:
            target_lvn = round(lvn, 3)
            signal = _classify_signal(prev_close, last_close, lvn)
            signal = _apply_rsi_filter(signal, rsi_value)
            reason = f"Price touched LVN {target_lvn}"
            if signal == "WAIT":
                reason = f"Price touched LVN {target_lvn}, RSI filter blocked entry"
            break

    return {
        "ticker": ticker_name,
        "date": str(last_date.date()),
        "price": round(last_close, 3),
        "lvn": target_lvn,
        "rsi": rsi_value,
        "signal": signal,
        "reason": reason,
    }


def run_scanner() -> List[Dict]:
    if not os.path.exists(CONFIG.runtime.data_dir):
        return []

    results = []

    for file in sorted(os.listdir(CONFIG.runtime.data_dir)):
        if not file.endswith(".csv") or file == "failed_tickers.csv":
            continue

        ticker = file.replace(".csv", "")

        try:
            res = analyze_ticker(ticker)
            if res:
                results.append(res)
        except Exception as e:
            logger.exception("Errore analisi ticker %s", ticker)
            results.append(
                {
                    "ticker": ticker,
                    "date": None,
                    "price": None,
                    "lvn": None,
                    "rsi": None,
                    "signal": "ERROR",
                    "reason": str(e),
                }
            )

    return results


def update_position(position: PositionState, df: pd.DataFrame, idx: int, date_str: str, current_price: float) -> Optional[Dict]:
    if position.entry_price <= 0 or position.quantity <= 0:
        return None

    signal, _, _, _ = _signal_for_index(df, idx)

    if not position.tp1_hit:
        hard_stop_pct = 0.03
        if position.direction == "LONG":
            hard_stop_price = position.entry_price * (1 - hard_stop_pct)
            if current_price <= hard_stop_price:
                return _close_trade(position, date_str, current_price, "Hard stop exit")
        else:
            hard_stop_price = position.entry_price * (1 + hard_stop_pct)
            if current_price >= hard_stop_price:
                return _close_trade(position, date_str, current_price, "Hard stop exit")

        if (position.direction == "LONG" and signal == "SHORT") or (position.direction == "SHORT" and signal == "LONG"):
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
                    "return_pct": round((float(position.pnl_euro) / position.invested_amount) * 100, 4)
                    if position.invested_amount
                    else 0.0,
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
            return _close_trade(position, date_str, current_price, "Trailing stop exit")

    return None
