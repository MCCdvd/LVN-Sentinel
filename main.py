from datetime import datetime

import data_manager
import engine
import portfolio_manager
import telegram_manager
from logging_setup import setup_logging

logger = setup_logging()


def _send_alert(message: str, context: str) -> bool:
    sent = telegram_manager.send_alert(message)
    if not sent:
        logger.warning("Invio alert Telegram fallito (%s)", context)
    return sent


def run_sentinel():
    logger.info("AVVIO SISTEMA MULTI-TARGET")
    print(f"🔔 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - AVVIO SISTEMA MULTI-TARGET")

    try:
        logger.info("Aggiornamento dati...")
        data_manager.update_data()
    except Exception as e:
        logger.exception("Errore aggiornamento dati")
        print(f"❌ Errore aggiornamento dati: {e}")
        return

    try:
        logger.info("Inizializzazione portafoglio...")
        portfolio_manager.init_portfolio()
    except Exception as e:
        logger.exception("Errore inizializzazione portafoglio")
        print(f"❌ Errore inizializzazione portafoglio: {e}")
        return

    try:
        logger.info("Avvio scanner...")
        all_results = engine.run_scanner()
    except Exception as e:
        logger.exception("Errore scanner")
        print(f"❌ Errore scanner: {e}")
        return

    found_signals = [s for s in all_results if s.get("signal") in {"LONG", "SHORT"}]
    prices_map = {s["ticker"]: s["price"] for s in all_results if s.get("price") is not None}

    try:
        updates = portfolio_manager.update_all_positions(prices_map)
        for up_msg in updates:
            _send_alert(f"⚠️ <b>UPDATE:</b> {up_msg}", f"update posizione {up_msg}")
            logger.info("Update posizione: %s", up_msg)
    except Exception as e:
        logger.exception("Errore update posizioni")
        _send_alert(f"❌ <b>ERRORE UPDATE POSIZIONI:</b> {e}", "errore update posizioni")

    if found_signals:
        msg_signals = "🎯 <b>SEGNALI RILEVATI:</b>\n" + "".join(
            [f"• {s['ticker']}: {s['signal']} ({s['price']}€)\n" for s in found_signals]
        )
        _send_alert(msg_signals, "riepilogo segnali")
        logger.info("Segnali rilevati: %d", len(found_signals))

        for s in found_signals:
            try:
                res_open = portfolio_manager.open_position(s["ticker"], s["signal"], s["price"])
                logger.info("Apertura posizione %s: %s", s["ticker"], res_open)
                if "🚀" in res_open:
                    _send_alert(f"✅ <b>ESECUZIONE:</b>\n{res_open}", f"esecuzione ordine {s['ticker']}")
            except Exception as e:
                logger.exception("Errore apertura posizione su %s", s["ticker"])
                _send_alert(f"❌ Errore apertura posizione su {s['ticker']}: {e}", f"errore apertura {s['ticker']}")

    try:
        report = portfolio_manager.get_performance_report(prices_map)
        if _send_alert(report, "report finale"):
            logger.info("Report finale inviato")
        else:
            logger.warning("Report finale non inviato")
    except Exception as e:
        logger.exception("Errore report finale")
        _send_alert(f"❌ <b>ERRORE REPORT:</b> {e}", "errore report finale")


if __name__ == "__main__":
    run_sentinel()
