import logging
import os

from config import CONFIG


def setup_logging():
    log_level = getattr(logging, CONFIG.logging.log_level.upper(), logging.INFO)

    os.makedirs(CONFIG.logging.log_dir, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(log_level)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(CONFIG.logging.log_file, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("Logging inizializzato")
    logger.info("Log file: %s", CONFIG.logging.log_file)

    return logger