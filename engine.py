import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

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


def _compute_rsi_series(close_series: pd.Series) -> pd.Series:
    period = int(CONFIG.strategy.rsi_period)
    delta = close_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    return rsi


def apply_rsi_entry_filter(signal: str, rsi_value: Optional[float]) -> str:
    if signal not in {"LONG", "SHORT"}:
        return signal
    if rsi_value is None or pd.isna(rsi_value):
        return "WAIT"
    if signal == "LONG" and float(rsi_value) > float(CONFIG.strategy.rsi_long_max):
        return "WAIT"
    if signal == "SHORT" and float(rsi_value) < float(CONFIG.strategy.rsi_short_min):
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
            "signal": "WAIT",
            "reason": "No valid LVN detected",
        }

    target_lvn = None
    signal = "WAIT"
    reason = "No touch on LVN"
    last_rsi = _compute_rsi_series(df["Close"]).iloc[-1]

    for lvn in lvns:
        if abs(last_close - lvn) <= CONFIG.strategy.price_tolerance:
            target_lvn = round(lvn, 3)
            base_signal = _classify_signal(prev_close, last_close, lvn)
            if base_signal in {"LONG", "SHORT"}:
                signal = apply_rsi_entry_filter(base_signal, last_rsi)
                if signal == "WAIT":
                    reason = f"RSI filter blocked {base_signal} (RSI={round(float(last_rsi), 2)})"
                else:
                    reason = f"Price touched LVN {target_lvn}"
            else:
                signal = base_signal
                reason = f"Price touched LVN {target_lvn}"
            break

    return {
        "ticker": ticker_name,
        "date": str(last_date.date()),
        "price": round(last_close, 3),
        "lvn": target_lvn,
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
                    "signal": "ERROR",
                    "reason": str(e),
                }
            )

    return results
