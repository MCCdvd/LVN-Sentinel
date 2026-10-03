import logging
import os
from datetime import datetime

import pandas as pd

from config import CONFIG

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(CONFIG.runtime.database_dir, "portfolio.csv")
HIST_PATH = os.path.join(CONFIG.runtime.database_dir, "history.csv")
DAILY_PNL_PATH = os.path.join(CONFIG.runtime.database_dir, "daily_pnl.csv")
TREND_CHART_PATH = os.path.join(CONFIG.runtime.database_dir, "pnl_trend_5d.png")

REPORT_TITLE = "LVN Sentinel Report - rev 031026"
TREND_DAYS = 5

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
    "last_price",
]

HISTORY_COLUMNS = ["date", "ticker", "pnl_euro", "note"]
DAILY_PNL_COLUMNS = [
    "date",
    "realized_day",
    "realized_total",
    "unrealized",
    "total_pnl",
    "equity",
    "open_positions",
    "stale_prices",
]
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


def _write_csv_atomic(df: pd.DataFrame, path: str):
    """Scrive il CSV su file temporaneo e poi lo sostituisce, evitando file corrotti in caso di crash."""
    tmp_path = f"{path}.tmp"
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


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

    _write_csv_atomic(port, DB_PATH)
    _write_csv_atomic(hist, HIST_PATH)
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
        "last_price": float(price),
    }

    if port.empty:
        port = pd.DataFrame([new_pos], columns=PORTFOLIO_COLUMNS)
    else:
        port = pd.concat([port, pd.DataFrame([new_pos])], ignore_index=True)

    _write_csv_atomic(port, DB_PATH)

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
    _write_csv_atomic(hist, HIST_PATH)

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

        port.at[idx, "last_price"] = current_price

        if entry_price <= 0 or quantity <= 0:
            continue

        current_signal = str(daily_signals_map.get(ticker, "")).upper().strip()

        if not tp1_hit:
            if position_type == "LONG":
                hard_stop_price = entry_price * 0.97
                if current_price <= hard_stop_price:
                    final_pnl = (current_price - entry_price) * quantity
                    total_pnl = pnl_euro + final_pnl - CONFIG.strategy.commissione_chiusura
                    save_to_history(ticker, total_pnl, note="Hard stop loss -3%")
                    indices_to_remove.append(idx)
                    messages.append(
                        f"🛑 HARD STOP LOSS su {ticker} a {current_price}€. PnL finale: {round(total_pnl, 2)}€"
                    )
                    continue
            else:
                hard_stop_price = entry_price * 1.03
                if current_price >= hard_stop_price:
                    final_pnl = (entry_price - current_price) * quantity
                    total_pnl = pnl_euro + final_pnl - CONFIG.strategy.commissione_chiusura
                    save_to_history(ticker, total_pnl, note="Hard stop loss +3%")
                    indices_to_remove.append(idx)
                    messages.append(
                        f"🛑 HARD STOP LOSS su {ticker} a {current_price}€. PnL finale: {round(total_pnl, 2)}€"
                    )
                    continue

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
        else:
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

    _write_csv_atomic(port, DB_PATH)
    return messages


def compute_pnl_snapshot(prices_map: dict, today: str | None = None) -> dict:
    """
    Calcola lo stato P&L deterministico a partire da history.csv (realizzato)
    e dalle posizioni aperte (latente). Se manca il prezzo di oggi per un ticker,
    usa l'ultimo prezzo noto (last_price) e in assenza il prezzo di ingresso.
    """
    today = today or datetime.now().strftime("%Y-%m-%d")
    prices_map = prices_map or {}

    hist = _read_csv_safe(HIST_PATH, HISTORY_COLUMNS)
    port = _read_csv_safe(DB_PATH, PORTFOLIO_COLUMNS)

    hist_pnl = pd.to_numeric(hist["pnl_euro"], errors="coerce").fillna(0)
    hist_dates = hist["date"].astype(str).str[:10]
    realized_total = float(hist_pnl.sum())
    realized_day = float(hist_pnl[hist_dates == today].sum())

    unrealized = 0.0
    stale_tickers = []
    for _, pos in port.iterrows():
        ticker = str(pos["ticker"])
        entry_price = _to_float(pos["entry_price"])
        quantity = _to_float(pos["quantity"])
        if entry_price <= 0 or quantity <= 0:
            continue

        price = _to_float(prices_map.get(ticker), default=0.0)
        if price <= 0:
            stale_tickers.append(ticker)
            price = _to_float(pos["last_price"], default=0.0)
            if price <= 0:
                price = entry_price

        position_type = str(pos["type"]).upper()
        mark_to_market = (price - entry_price) * quantity if position_type == "LONG" else (entry_price - price) * quantity
        unrealized += mark_to_market + _to_float(pos["pnl_euro"])

    total_pnl = realized_total + unrealized
    return {
        "date": today,
        "realized_day": round(realized_day, 2),
        "realized_total": round(realized_total, 2),
        "unrealized": round(unrealized, 2),
        "total_pnl": round(total_pnl, 2),
        "equity": round(CONFIG.strategy.capitale_iniziale + total_pnl, 2),
        "open_positions": int(len(port)),
        "stale_prices": ",".join(stale_tickers),
    }


def load_daily_pnl() -> pd.DataFrame:
    daily = _read_csv_safe(DAILY_PNL_PATH, DAILY_PNL_COLUMNS)
    if daily.empty:
        return daily
    daily["date"] = daily["date"].astype(str).str[:10]
    for col in ["realized_day", "realized_total", "unrealized", "total_pnl", "equity"]:
        daily[col] = pd.to_numeric(daily[col], errors="coerce").fillna(0.0)
    daily["stale_prices"] = daily["stale_prices"].fillna("").astype(str)
    return daily.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)


def _merge_snapshot(daily: pd.DataFrame, snapshot: dict) -> pd.DataFrame:
    row = pd.DataFrame([snapshot], columns=DAILY_PNL_COLUMNS)
    if daily.empty:
        return row
    daily = daily[daily["date"] != snapshot["date"]]
    return pd.concat([daily, row], ignore_index=True).sort_values("date").reset_index(drop=True)


def record_daily_snapshot(snapshot: dict) -> pd.DataFrame:
    """Salva (upsert) lo snapshot del giorno: run ripetuti nello stesso giorno sovrascrivono la riga."""
    _ensure_dirs()
    daily = _merge_snapshot(load_daily_pnl(), snapshot)
    _write_csv_atomic(daily, DAILY_PNL_PATH)
    logger.info("Snapshot P&L giornaliero salvato per %s", snapshot["date"])
    return daily


def _fmt_eur(value: float) -> str:
    return f"{value:+,.2f}€"


def _first_run_date(daily: pd.DataFrame) -> str:
    dates = list(daily["date"]) if not daily.empty else []
    hist = _read_csv_safe(HIST_PATH, HISTORY_COLUMNS)
    dates += [d for d in hist["date"].dropna().astype(str).str[:10] if d and d != "nan"]
    return min(dates) if dates else "n/d"


def _trend_rows(daily: pd.DataFrame, days: int = TREND_DAYS) -> list:
    """Ultimi N giorni come (data, P&L totale, variazione vs giorno precedente o None)."""
    totals = [float(v) for v in daily["total_pnl"]]
    dates = list(daily["date"])
    start = max(len(totals) - days, 0)
    return [
        (dates[i], totals[i], totals[i] - totals[i - 1] if i > 0 else None)
        for i in range(start, len(totals))
    ]


def _trend_text(daily: pd.DataFrame, days: int = TREND_DAYS) -> str:
    rows = _trend_rows(daily, days)
    if not rows:
        return "n/d"

    lo, hi = min(r[1] for r in rows), max(r[1] for r in rows)
    blocks = "▁▂▃▄▅▆▇█"
    lines = []
    for date, total, change in rows:
        level = 0 if hi == lo else int(round((total - lo) / (hi - lo) * (len(blocks) - 1)))
        delta = "" if change is None else f" ({_fmt_eur(change)})"
        lines.append(f"{date[5:]} {blocks[level]} {_fmt_eur(total)}{delta}")
    return "\n".join(lines)


def get_performance_report(prices_map: dict, today: str | None = None) -> str:
    """
    Costruisce il report giornaliero e salva lo snapshot P&L del giorno.
    Se il salvataggio fallisce il report viene comunque generato in memoria.
    """
    liquidita = get_liquidity()
    snapshot = compute_pnl_snapshot(prices_map, today=today)

    try:
        daily = record_daily_snapshot(snapshot)
    except Exception:
        logger.exception("Errore salvataggio snapshot P&L giornaliero, uso dati in memoria")
        try:
            daily = _merge_snapshot(load_daily_pnl(), snapshot)
        except Exception:
            logger.exception("Errore lettura storico P&L giornaliero")
            daily = pd.DataFrame([snapshot], columns=DAILY_PNL_COLUMNS)

    previous = daily[daily["date"] < snapshot["date"]]
    if previous.empty:
        day_change_txt = "n/d (primo giorno)"
        unrealized_change_txt = "n/d"
    else:
        prev_row = previous.iloc[-1]
        day_change_txt = _fmt_eur(snapshot["total_pnl"] - float(prev_row["total_pnl"]))
        unrealized_change_txt = _fmt_eur(snapshot["unrealized"] - float(prev_row["unrealized"]))

    capitale = CONFIG.strategy.capitale_iniziale
    rendimento_pct = (snapshot["total_pnl"] / capitale) * 100 if capitale else 0.0

    stale_line = ""
    if snapshot["stale_prices"]:
        stale_line = f"⚠️ Prezzi mancanti (ultimo noto): {snapshot['stale_prices']}\n"

    return (
        f"📊 <b>{REPORT_TITLE}</b>\n"
        f"📅 {snapshot['date']}\n"
        f"────────────────\n"
        f"📘 <b>Daily realized P&amp;L:</b> {_fmt_eur(snapshot['realized_day'])}\n"
        f"📈 <b>Daily unrealized P&amp;L:</b> {_fmt_eur(snapshot['unrealized'])} (Δ {unrealized_change_txt})\n"
        f"🔄 <b>Variazione giornaliera:</b> {day_change_txt}\n"
        f"────────────────\n"
        f"💰 <b>Equity Totale:</b> {snapshot['equity']:,.2f}€\n"
        f"💵 <b>Liquidità:</b> {liquidita:,.2f}€\n"
        f"🏢 <b>Posizioni Attive:</b> {snapshot['open_positions']}\n"
        f"📘 <b>PnL Realizzato (totale):</b> {_fmt_eur(snapshot['realized_total'])}\n"
        f"{stale_line}"
        f"────────────────\n"
        f"🏁 <b>Total P&amp;L from first day run:</b> {_fmt_eur(snapshot['total_pnl'])} "
        f"({round(rendimento_pct, 2)}%, dal {_first_run_date(daily)})\n"
        f"────────────────\n"
        f"📉 <b>Trend ultimi {TREND_DAYS} giorni (P&amp;L totale):</b>\n"
        f"<pre>{_trend_text(daily)}</pre>"
    )


def build_trend_chart(path: str = TREND_CHART_PATH, days: int = TREND_DAYS) -> str | None:
    """Genera il grafico PNG degli ultimi giorni. Ritorna None se matplotlib non è disponibile o mancano dati."""
    daily = load_daily_pnl()
    if daily.empty:
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.info("matplotlib non installato: grafico trend non generato (uso fallback testuale)")
        return None

    rows = _trend_rows(daily, days)
    totals = [r[1] for r in rows]
    changes = [0.0 if r[2] is None else r[2] for r in rows]

    labels = [r[0][5:] for r in rows]
    x = list(range(len(labels)))
    fig, ax = plt.subplots(figsize=(6, 3.2), dpi=120)
    try:
        ax.bar(x, changes, color=["#2e7d32" if c >= 0 else "#c62828" for c in changes], alpha=0.5, label="Δ giornaliero")
        ax.plot(x, totals, marker="o", color="#1565c0", label="P&L totale")
        ax.axhline(0, color="grey", linewidth=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_title(f"{REPORT_TITLE} - ultimi {len(rows)} giorni")
        ax.set_ylabel("€")
        ax.legend(loc="best", fontsize=8)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        _ensure_dirs()
        fig.savefig(path)
    finally:
        plt.close(fig)

    return path
