import logging

import requests

from config import CONFIG

logger = logging.getLogger(__name__)


def _build_telegram_url() -> str:
    token = CONFIG.secrets.telegram_bot_token
    return f"https://api.telegram.org/bot{token}/sendMessage"


def send_alert(message: str, parse_mode: str = "HTML", disable_web_page_preview: bool = True) -> bool:
    """
    Invia un messaggio al canale/chat Telegram configurato.
    Restituisce True se l'invio va a buon fine, False altrimenti.
    """
    chat_id = CONFIG.secrets.telegram_chat_id
    token = CONFIG.secrets.telegram_bot_token

    if not token or not chat_id:
        logger.error("Token o chat_id Telegram mancanti")
        return False

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }

    try:
        response = requests.post(
            _build_telegram_url(),
            data=payload,
            timeout=CONFIG.runtime.request_timeout,
        )
        response.raise_for_status()

        data = response.json()
        if not data.get("ok", False):
            logger.error("Telegram API ha risposto con ok=False: %s", data)
            return False

        logger.info("Messaggio Telegram inviato correttamente")
        return True

    except requests.RequestException as exc:
        logger.exception("Errore invio messaggio Telegram: %s", exc)
        return False
    except ValueError:
        logger.exception("Risposta Telegram non valida o non JSON")
        return False
    except Exception as exc:
        logger.exception("Errore inatteso durante invio Telegram: %s", exc)
        return False
from telegram_manager_Version2 import *  # noqa: F401,F403
