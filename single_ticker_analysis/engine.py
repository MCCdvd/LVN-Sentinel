from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


@dataclass(frozen=True)
class StrategyParams:
    window_profile: int
    price_tolerance: float
    lvn_threshold: float
    bin_step: float
    min_profile_levels: int
    rsi_period: int
    rsi_long_max: float
    rsi_short_min: float


def safe_read_csv(file_path: str) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(file_path)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    if not {"Date", "Close", "Volume"}.issubset(df.columns):
        return None

    work = df.copy()
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce")
    work["Close"] = pd.to_numeric(work["Close"], errors="coerce")
    work["Volume"] = pd.to_numeric(work["Volume"], errors="coerce")
    work = work.dropna(subset=["Date", "Close", "Volume"]).sort_values("Date").reset_index(drop=True)
    return work if not work.empty else None


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
    return round(float(100 - (100 / (1 + rs))), 2)


def get_lvn_nodes(df_window: pd.DataFrame, bin_step: float, lvn_threshold: float, min_profile_levels: int) -> List[float]:
    work = df_window.copy()
    work["PriceBin"] = (work["Close"] / bin_step).round() * bin_step
    profile = work.groupby("PriceBin")["Volume"].sum().sort_index()

    if profile is None or len(profile) < min_profile_levels:
        return []

    values = profile.values
    if np.all(values == 0):
        return []

    poc_volume = float(profile.max())
    candidate_idx = np.array([], dtype=int)
    if len(profile) >= 7:
        candidate_idx = argrelextrema(values, np.less, order=2)[0]

    lvns: List[float] = []
    for idx in candidate_idx:
        price_level = float(profile.index[idx])
        level_volume = float(profile.iloc[idx])
        if level_volume < poc_volume * lvn_threshold:
            lvns.append(round(price_level, 3))
    return sorted(list(set(lvns)))


def _classify_signal(prev_close: float, last_close: float, lvn: float, price_tolerance: float) -> str:
    if abs(last_close - lvn) > price_tolerance:
        return "WAIT"
    if prev_close > lvn:
        return "LONG"
    if prev_close < lvn:
        return "SHORT"
    return "WAIT"


def _apply_rsi_filter(signal: str, rsi_value: Optional[float], rsi_long_max: float, rsi_short_min: float) -> str:
    if signal == "LONG" and (rsi_value is None or rsi_value > rsi_long_max):
        return "WAIT"
    if signal == "SHORT" and (rsi_value is None or rsi_value < rsi_short_min):
        return "WAIT"
    return signal


def signal_for_index(df: pd.DataFrame, idx: int, params: StrategyParams) -> Tuple[str, Optional[float], str, Optional[float]]:
    if idx < params.window_profile:
        return "WAIT", None, "Insufficient profile window", None

    analysis_window = df.iloc[idx - params.window_profile : idx].copy()
    last_row = df.iloc[idx]
    prev_row = df.iloc[idx - 1]
    last_close = float(last_row["Close"])
    prev_close = float(prev_row["Close"])
    rsi_value = _calculate_rsi(df["Close"].iloc[: idx + 1], params.rsi_period)

    lvns = get_lvn_nodes(analysis_window, params.bin_step, params.lvn_threshold, params.min_profile_levels)
    if not lvns:
        return "WAIT", None, "No valid LVN detected", rsi_value

    for lvn in lvns:
        if abs(last_close - lvn) <= params.price_tolerance:
            signal = _classify_signal(prev_close, last_close, lvn, params.price_tolerance)
            signal = _apply_rsi_filter(signal, rsi_value, params.rsi_long_max, params.rsi_short_min)
            reason = f"Price touched LVN {round(float(lvn), 3)}"
            if signal == "WAIT":
                reason = f"Price touched LVN {round(float(lvn), 3)}, filter blocked entry"
            return signal, round(float(lvn), 3), reason, rsi_value

    return "WAIT", None, "No touch on LVN", rsi_value

