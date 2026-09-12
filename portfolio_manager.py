import logging
import os
from datetime import datetime

import pandas as pd

from config import CONFIG

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(CONFIG.runtime.database_dir, "portfolio.csv")
HIST_PATH = os.path.join(CONFIG.runtime.database_dir, "history.csv")

PORTFOLIO_COLUMNS = [
    "ticker",
    "status",
    "type",
    "entry_price",
    "quantity",
    "current_stop",
    "tp1_hit",
    "pnl_euro",
    "entry_date",
    "invested_amount",
]

HISTORY_COLUMNS = ["date", "ticker", "pnl_euro", "note"]
HARD_STOP_PCT = 0.03


def _ensure_dirs():
    os.makedirs(CONFIG.runtime.database_dir, exist_ok=True)


def _read_csv_safe(path: str, columns: list) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=columns)

    try:
        df = pd.read_csv(path)
    except Exception:
        logger.exception("Errore lettura file %s", path)
        return pd.DataFrame(columns=columns)

    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA

    return df[columns].copy()


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def init_portfolio():
    _ensure_dirs()
    port = _read_csv_safe(DB_PATH, PORTFOLIO_COLUMNS)
    hist = _read_csv_safe(HIST_PATH, HISTORY_COLUMNS)

    invested_amount = pd.to_numeric(port["invested_amount"], errors="coerce")
    computed_invested_amount = (
        pd.to_numeric(port["quantity"], errors="coerce").fillna(0)
        * pd.to_numeric(port["entry_price"], errors="coerce").fillna(0)
    )
    port["invested_amount"] = invested_amount.where(invested_amount.notna(), computed_invested_amount)

    port.to_csv(DB_PATH, index=False)
    hist.to_csv(HIST_PATH, index=False)
    logger.info("Portfolio inizializzato")


def get_liquidity() -> float:
    hist = _read_csv_safe(HIST_PATH, HISTORY_COLUMNS)
    port = _read_csv_safe(DB_PATH, PORTFOLIO_COLUMNS)

    pnl_realizzato = pd.to_numeric(hist["pnl_euro"], errors="coerce").fillna(0).sum()
    capitale_impegnato = pd.to_numeric(port["invested_amount"], errors="coerce").fillna(0).sum()

    liquidita = CONFIG.strategy.capitale_iniziale + pnl_realizzato - capitale_impegnato
    return round(float(liquidita), 2)


def open_position(ticker: str, signal_type: str, price: float) -> str:
    signal_type = signal_type.upper().strip()

    if signal_type not in {"LONG", "SHORT"}:
        return f"⚠️ Segnale non valido per {ticker}: {signal_type}"

    port = _read_csv_safe(DB_PATH, PORTFOLIO_COLUMNS)
    liquidita = get_liquidity()

    if not port.empty and ticker in port["ticker"].astype(str).values:
        return f"ℹ️ {ticker} è già in portafoglio."

    if liquidita < CONFIG.strategy.investimento_per_trade:
        return f"⚠️ Liquidità insufficiente ({liquidita}€) per {ticker}."

    if price <= 0:
        return f"⚠️ Prezzo non valido per {ticker}."

    quantity = int(CONFIG.strategy.investimento_per_trade / price)
    if quantity <= 0:
        return f"⚠️ Prezzo troppo alto per {ticker}."

    invested_amount = round(quantity * price, 2)

    new_pos = {
        "ticker": ticker,
        "status": "OPEN",
        "type": signal_type,
        "entry_price": float(price),
        "quantity": int(quantity),
        "current_stop": 0.0,
        "tp1_hit": False,
        "pnl_euro": -CONFIG.strategy.commissione_apertura,
        "entry_date": datetime.now().strftime("%Y-%m-%d"),
        "invested_amount": invested_amount,
    }

    if port.empty:
        port = pd.DataFrame([new_pos], columns=PORTFOLIO_COLUMNS)
    else:
        port = pd.concat([port, pd.DataFrame([new_pos])], ignore_index=True)

    port.to_csv(DB_PATH, index=False)

    logger.info("Aperta posizione %s %s @ %s", signal_type, ticker, price)
    return f"🚀 APERTA POSIZIONE {signal_type} su {ticker} a {price}€ ({quantity} azioni)"


def save_to_history(ticker: str, pnl: float, note: str = ""):
    hist = _read_csv_safe(HIST_PATH, HISTORY_COLUMNS)

    new_entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "ticker": ticker,
        "pnl_euro": round(float(pnl), 2),
        "note": note,
    }

    hist = pd.concat([hist, pd.DataFrame([new_entry])], ignore_index=True)
    hist.to_csv(HIST_PATH, index=False)

    logger.info("Salvata history per %s: %s", ticker, pnl)


def update_all_positions(current_prices_map: dict, daily_signals_map: dict | None = None):
    port = _read_csv_safe(DB_PATH, PORTFOLIO_COLUMNS)
    if port.empty:
        return []

    daily_signals_map = daily_signals_map or {}
    messages = []
    indices_to_remove = []

    for idx, pos in port.iterrows():
        ticker = str(pos["ticker"])

        if ticker not in current_prices_map:
            continue

        try:
            current_price = float(current_prices_map[ticker])
            entry_price = float(pos["entry_price"])
            quantity = int(pos["quantity"])
            position_type = str(pos["type"]).upper()
            tp1_hit = _to_bool(pos["tp1_hit"])
            current_stop = float(pos["current_stop"]) if pd.notna(pos["current_stop"]) else 0.0
            pnl_euro = float(pos["pnl_euro"]) if pd.notna(pos["pnl_euro"]) else 0.0
            invested_amount = float(pos["invested_amount"]) if pd.notna(pos["invested_amount"]) else 0.0
        except Exception:
            logger.exception("Errore parsing posizione %s", ticker)
            continue

        if entry_price <= 0 or quantity <= 0:
            continue

        hard_stop_long = entry_price * (1 - HARD_STOP_PCT)
        hard_stop_short = entry_price * (1 + HARD_STOP_PCT)

        if position_type == "LONG" and current_price <= hard_stop_long:
            final_pnl = (current_price - entry_price) * quantity
            total_pnl = pnl_euro + final_pnl - CONFIG.strategy.commissione_chiusura
            save_to_history(ticker, total_pnl, note="Hard stop loss -3%")
            indices_to_remove.append(idx)
            messages.append(f"🛑 HARD STOP LOSS su {ticker} a {current_price}€. PnL finale: {round(total_pnl, 2)}€")
            continue

        if position_type == "SHORT" and current_price >= hard_stop_short:
            final_pnl = (entry_price - current_price) * quantity
            total_pnl = pnl_euro + final_pnl - CONFIG.strategy.commissione_chiusura
            save_to_history(ticker, total_pnl, note="Hard stop loss +3%")
            indices_to_remove.append(idx)
            messages.append(f"🛑 HARD STOP LOSS su {ticker} a {current_price}€. PnL finale: {round(total_pnl, 2)}€")
            continue

        current_signal = str(daily_signals_map.get(ticker, "")).upper().strip()

        if not tp1_hit:
            opposite_signal = (
                (position_type == "LONG" and current_signal == "SHORT")
                or (position_type == "SHORT" and current_signal == "LONG")
            )

            if opposite_signal:
                port.at[idx, "tp1_hit"] = True
                port.at[idx, "status"] = "PARTIAL"

                half_qty = quantity // 2 or quantity
                closed_pnl = (
                    (current_price - entry_price) * half_qty
                    if position_type == "LONG"
                    else (entry_price - current_price) * half_qty
                )

                pnl_euro = pnl_euro + closed_pnl - CONFIG.strategy.commissione_chiusura
                remaining_qty = quantity - half_qty

                if remaining_qty <= 0:
                    total_pnl = round(pnl_euro, 2)
                    save_to_history(ticker, total_pnl, note="Opposite daily signal close")
                    indices_to_remove.append(idx)
                    messages.append(f"💰 Segnale opposto su {ticker}: posizione chiusa interamente.")
                    continue

                port.at[idx, "pnl_euro"] = round(pnl_euro, 2)
                port.at[idx, "quantity"] = remaining_qty
                port.at[idx, "invested_amount"] = round(invested_amount * (remaining_qty / quantity), 2)
                port.at[idx, "current_stop"] = (
                    round(current_price * 0.98, 4)
                    if position_type == "LONG"
                    else round(current_price * 1.02, 4)
                )

                messages.append(f"💰 Segnale opposto su {ticker}: chiuso circa 50%.")
                continue

        if tp1_hit:
            is_exit = False

            if position_type == "LONG":
                new_stop = current_price * 0.98
                if new_stop > current_stop:
                    current_stop = new_stop
                if current_price <= current_stop:
                    is_exit = True
            else:
                new_stop = current_price * 1.02
                if current_stop == 0.0 or new_stop < current_stop:
                    current_stop = new_stop
                if current_price >= current_stop:
                    is_exit = True

            port.at[idx, "current_stop"] = round(float(current_stop), 4)

            if is_exit:
                remaining_qty = quantity
                final_pnl = (
                    (current_price - entry_price) * remaining_qty
                    if position_type == "LONG"
                    else (entry_price - current_price) * remaining_qty
                )
                total_pnl = pnl_euro + final_pnl - CONFIG.strategy.commissione_chiusura
                save_to_history(ticker, total_pnl, note="Trailing stop exit")
                indices_to_remove.append(idx)
                messages.append(
                    f"🛑 TRAILING STOP su {ticker} a {current_price}€. PnL finale: {round(total_pnl, 2)}€"
                )

        port.loc[idx, "pnl_euro"] = round(float(port.loc[idx, "pnl_euro"]), 2)

    if indices_to_remove:
        port = port.drop(indices_to_remove)

    port.to_csv(DB_PATH, index=False)
    return messages


def get_performance_report(prices_map: dict) -> str:
    liquidita = get_liquidity()
    port = _read_csv_safe(DB_PATH, PORTFOLIO_COLUMNS)
    hist = _read_csv_safe(HIST_PATH, HISTORY_COLUMNS)

    pnl_realizzato = pd.to_numeric(hist["pnl_euro"], errors="coerce").fillna(0).sum()

    pnl_latente = 0.0
    for _, pos in port.iterrows():
        ticker = str(pos["ticker"])
        cp = float(prices_map.get(ticker, pos["entry_price"]))
        entry_price = float(pos["entry_price"])
        quantity = int(pos["quantity"])
        position_type = str(pos["type"]).upper()
        pnl_already = float(pos["pnl_euro"]) if pd.notna(pos["pnl_euro"]) else 0.0

        pnl_latente += (
            ((cp - entry_price) * quantity if position_type == "LONG" else (entry_price - cp) * quantity)
            + pnl_already
        )

    equity_totale = CONFIG.strategy.capitale_iniziale + pnl_realizzato + pnl_latente
    rendimento_pct = ((equity_totale / CONFIG.strategy.capitale_iniziale) - 1) * 100 if CONFIG.strategy.capitale_iniziale else 0

    return (
        f"📊 <b>REPORT LVN PORTFOLIO</b>\n"
        f"────────────────\n"
        f"💰 <b>Equity Totale:</b> {round(equity_totale, 2)}€\n"
        f"💵 <b>Liquidità:</b> {liquidita}€\n"
        f"🏢 <b>Posizioni Attive:</b> {len(port)}\n"
        f"📈 <b>PnL Latente:</b> {round(pnl_latente, 2)}€\n"
        f"📘 <b>PnL Realizzato:</b> {round(float(pnl_realizzato), 2)}€\n"
        f"────────────────\n"
        f"📊 <b>Rendimento Totale:</b> {round(float(rendimento_pct), 2)}%"
    )
