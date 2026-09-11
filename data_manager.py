import logging
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from config import CONFIG

logger = logging.getLogger(__name__)

MIB = [
    "A2A.MI", "AMP.MI", "AZM.MI", "BMPS.MI", "BAMI.MI", "BCP.MI", "BFF.MI",
    "BPER.MI", "BZU.MI", "CNHI.MI", "DIA.MI", "DLG.MI", "ENEL.MI", "ENI.MI",
    "ERG.MI", "EXO.MI", "FBK.MI", "G.MI", "GRP.MI", "HER.MI", "IP.MI",
    "IPG.MI", "ISP.MI", "IRE.MI", "ITM.MI", "IVG.MI", "LDO.MI", "MB.MI",
    "MONC.MI", "NEXI.MI", "PIRC.MI", "PST.MI", "PRY.MI", "REC.MI", "RACE.MI",
    "SAES.MI", "SFER.MI", "SPM.MI", "SRG.MI", "STLAM.MI", "STMMI.MI",
    "TEN.MI", "TIT.MI", "TRN.MI", "UCG.MI", "UNI.MI"
]

DAX = [
    "ADS.DE", "AIR.DE", "ALV.DE", "BAS.DE", "BAYN.DE", "BEI.DE", "BMW.DE",
    "BNR.DE", "CBK.DE", "CON.DE", "DB1.DE", "DBK.DE", "DHL.DE", "DTE.DE",
    "DTG.DE", "DWNI.DE", "EOAN.DE", "FME.DE", "FRE.DE", "HEI.DE", "HEN3.DE",
    "HFG.DE", "HNR1.DE", "IFX.DE", "KBX.DE", "LHA.DE", "MRK.DE", "MTX.DE",
    "MUV2.DE", "P911.DE", "PAH3.DE", "PUM.DE", "QIA.DE", "RHM.DE", "RWE.DE",
    "SAP.DE", "SRT3.DE", "SIE.DE", "SY1.DE", "VNA.DE", "VOW3.DE", "ZAL.DE"
]

CAC = [
    "AC.PA", "AIR.PA", "AI.PA", "ALO.PA", "BN.PA", "BNP.PA", "CA.PA",
    "CAP.PA", "CS.PA", "DG.PA", "DSY.PA", "EDEN.PA", "EL.PA", "EN.PA",
    "ENGI.PA", "ERF.PA", "EI.PA", "GLE.PA", "HO.PA", "KER.PA", "LR.PA",
    "MC.PA", "ML.PA", "ORA.PA", "OR.PA", "PUB.PA", "RI.PA", "RMS.PA",
    "RNO.PA", "SAF.PA", "SAN.PA", "SGO.PA", "SU.PA", "TEP.PA", "TTE.PA",
    "URW.PA", "VIE.PA", "VIV.PA"
]

TICKERS = MIB + DAX + CAC
FAILED_TICKERS = set()


def _ensure_data_dir():
    os.makedirs(CONFIG.runtime.data_dir, exist_ok=True)


def _normalize_download(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()

    if isinstance(df.columns, pd.MultiIndex):
        try:
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        except Exception:
            return pd.DataFrame()

    df = df.reset_index()

    if "Date" not in df.columns and "Datetime" in df.columns:
        df = df.rename(columns={"Datetime": "Date"})

    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    for col in required:
        if col not in df.columns:
            return pd.DataFrame()

    df = df[required].copy()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Date", "Close", "Volume"])
    df = df.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")

    return df.reset_index(drop=True)


def _safe_read_existing(file_path: str) -> pd.DataFrame:
    if not os.path.exists(file_path):
        return pd.DataFrame()

    try:
        df = pd.read_csv(file_path)
    except Exception:
        logger.exception("Errore lettura file %s", file_path)
        return pd.DataFrame()

    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Date", "Close", "Volume"])
    df = df.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")
    return df.reset_index(drop=True)


def _download_with_retry(ticker: str, start_date: str) -> pd.DataFrame:
    if ticker in FAILED_TICKERS:
        logger.warning("Ticker già segnato come fallito, salto: %s", ticker)
        return pd.DataFrame()

    last_error = None

    for attempt in range(1, CONFIG.runtime.max_retries + 1):
        try:
            raw = yf.download(
                ticker,
                start=start_date,
                progress=False,
                auto_adjust=False,
                actions=False,
                group_by="column"
            )

            normalized = _normalize_download(raw)
            if not normalized.empty:
                return normalized

        except Exception as e:
            last_error = e
            logger.exception(
                "Errore download %s (tentativo %s/%s)",
                ticker,
                attempt,
                CONFIG.runtime.max_retries
            )

        time.sleep(CONFIG.runtime.retry_sleep_seconds)

    FAILED_TICKERS.add(ticker)
    logger.error("Download fallito definitivamente per %s: %s", ticker, last_error)
    return pd.DataFrame()


def update_data():
    _ensure_data_dir()
    total = len(TICKERS)
    logger.info("Inizio aggiornamento di %s titoli", total)

    for index, ticker in enumerate(TICKERS, 1):
        clean_name = ticker.split(".")[0]
        file_path = os.path.join(CONFIG.runtime.data_dir, f"{clean_name}.csv")

        existing_df = _safe_read_existing(file_path)

        if not existing_df.empty:
            last_date = existing_df["Date"].max()
            if pd.notna(last_date) and last_date.date() >= (datetime.now() - timedelta(days=1)).date():
                logger.info("[%s/%s] %s già aggiornato", index, total, ticker)
                continue
            start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

        logger.info("[%s/%s] Scaricamento %s", index, total, ticker)
        new_data = _download_with_retry(ticker, start_date)

        if new_data.empty:
            logger.warning("[%s/%s] Nessun dato valido per %s", index, total, ticker)
            time.sleep(1.5)
            continue

        if not existing_df.empty:
            combined_df = pd.concat([existing_df, new_data], ignore_index=True)
        else:
            combined_df = new_data

        combined_df = combined_df.drop_duplicates(subset=["Date"], keep="last")
        combined_df = combined_df.sort_values("Date").reset_index(drop=True)
        combined_df.to_csv(file_path, index=False)

        time.sleep(1.5)

    if FAILED_TICKERS:
        failed_path = os.path.join(CONFIG.runtime.data_dir, "failed_tickers.csv")
        pd.DataFrame({"ticker": sorted(FAILED_TICKERS)}).to_csv(failed_path, index=False)
        logger.warning("Ticker falliti salvati in %s", failed_path)

    logger.info("Database locale aggiornato con successo")


if __name__ == "__main__":
    update_data()