import portfolio_manager_Version3 as _impl
from portfolio_manager_Version3 import *  # noqa: F401,F403


def open_position(ticker: str, signal_type: str, price: float) -> str:
    signal_type = signal_type.upper().strip()

    if signal_type not in {"LONG", "SHORT"}:
        return f"⚠️ Segnale non valido per {ticker}: {signal_type}"

    port = _impl._read_csv_safe(_impl.DB_PATH, _impl.PORTFOLIO_COLUMNS)
    liquidita = _impl.get_liquidity()

    if not port.empty and ticker in port["ticker"].astype(str).values:
        return f"ℹ️ {ticker} è già in portafoglio."

    if liquidita < _impl.CONFIG.strategy.investimento_per_trade:
        return f"⚠️ Liquidità insufficiente ({liquidita}€) per {ticker}."

    if price <= 0:
        return f"⚠️ Prezzo non valido per {ticker}."

    quantity = int(_impl.CONFIG.strategy.investimento_per_trade / price)
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
        "pnl_euro": -_impl.CONFIG.strategy.commissione_apertura,
        "entry_date": _impl.datetime.now().strftime("%Y-%m-%d"),
        "invested_amount": invested_amount,
    }

    if port.empty:
        port = _impl.pd.DataFrame([new_pos], columns=_impl.PORTFOLIO_COLUMNS)
    else:
        port = _impl.pd.concat([port, _impl.pd.DataFrame([new_pos])], ignore_index=True)

    port.to_csv(_impl.DB_PATH, index=False)

    _impl.logger.info("Aperta posizione %s %s @ %s", signal_type, ticker, price)
    return f"🚀 APERTA POSIZIONE {signal_type} su {ticker} a {price}€ ({quantity} azioni)"
