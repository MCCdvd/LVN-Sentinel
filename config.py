from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


def _get_env_str(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return str(value).strip()


def _get_env_int(name: str, default: int) -> int:
    raw = _get_env_str(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Valore non valido per {name}: {raw!r}") from exc


def _get_env_float(name: str, default: float) -> float:
    raw = _get_env_str(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Valore non valido per {name}: {raw!r}") from exc


@dataclass(frozen=True)
class SecretConfig:
    telegram_bot_token: str
    telegram_chat_id: str


@dataclass(frozen=True)
class StrategyConfig:
    capitale_iniziale: float = 100000.0
    investimento_per_trade: float = 10000.0
    commissione_apertura: float = 10.0
    commissione_chiusura: float = 10.0
    window_profile: int = 25
    price_tolerance: float = 0.05
    lvn_threshold: float = 0.50
    bin_step: float = 0.05
    min_profile_levels: int = 5


@dataclass(frozen=True)
class RuntimeConfig:
    data_dir: str = "data"
    database_dir: str = "database"
    request_timeout: int = 10
    max_retries: int = 3
    retry_sleep_seconds: int = 2


@dataclass(frozen=True)
class LoggingConfig:
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_file: str = ""


@dataclass(frozen=True)
class AppConfig:
    secrets: SecretConfig
    strategy: StrategyConfig
    runtime: RuntimeConfig
    logging: LoggingConfig


def _validate_secret_config(cfg: SecretConfig) -> None:
    if not cfg.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN mancante o vuoto")
    if not cfg.telegram_chat_id:
        raise ValueError("TELEGRAM_CHAT_ID mancante o vuoto")


def _validate_strategy_config(cfg: StrategyConfig) -> None:
    if cfg.capitale_iniziale <= 0:
        raise ValueError("CAPITALE_INIZIALE deve essere > 0")
    if cfg.investimento_per_trade <= 0:
        raise ValueError("INVESTIMENTO_PER_TRADE deve essere > 0")
    if cfg.investimento_per_trade > cfg.capitale_iniziale:
        raise ValueError("INVESTIMENTO_PER_TRADE non può superare CAPITALE_INIZIALE")
    if cfg.commissione_apertura < 0:
        raise ValueError("COMMISSIONE_APERTURA non può essere negativa")
    if cfg.commissione_chiusura < 0:
        raise ValueError("COMMISSIONE_CHIUSURA non può essere negativa")
    if cfg.window_profile < 2:
        raise ValueError("WINDOW_PROFILE deve essere >= 2")
    if cfg.price_tolerance <= 0:
        raise ValueError("PRICE_TOLERANCE deve essere > 0")
    if not 0 < cfg.lvn_threshold <= 1:
        raise ValueError("LVN_THRESHOLD deve essere compreso tra 0 e 1")
    if cfg.bin_step <= 0:
        raise ValueError("BIN_STEP deve essere > 0")
    if cfg.min_profile_levels < 1:
        raise ValueError("MIN_PROFILE_LEVELS deve essere >= 1")


def _validate_runtime_config(cfg: RuntimeConfig) -> None:
    if not cfg.data_dir:
        raise ValueError("DATA_DIR non può essere vuota")
    if not cfg.database_dir:
        raise ValueError("DATABASE_DIR non può essere vuota")
    if cfg.request_timeout <= 0:
        raise ValueError("REQUEST_TIMEOUT deve essere > 0")
    if cfg.max_retries < 1:
        raise ValueError("MAX_RETRIES deve essere >= 1")
    if cfg.retry_sleep_seconds < 0:
        raise ValueError("RETRY_SLEEP_SECONDS non può essere negativa")


def _normalize_log_file(log_dir: str, log_file: str) -> str:
    if log_file.strip():
        return log_file.strip()
    return str(Path(log_dir) / "app.log")


def _validate_logging_config(cfg: LoggingConfig) -> None:
    if not cfg.log_level:
        raise ValueError("LOG_LEVEL non può essere vuoto")
    if cfg.log_level.upper() not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}:
        raise ValueError(f"LOG_LEVEL non valido: {cfg.log_level}")
    if not cfg.log_dir:
        raise ValueError("LOG_DIR non può essere vuota")
    if not cfg.log_file:
        raise ValueError("LOG_FILE non può essere vuoto")


def load_config() -> AppConfig:
    secrets = SecretConfig(
        telegram_bot_token=_get_env_str("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get_env_str("TELEGRAM_CHAT_ID"),
    )

    strategy = StrategyConfig(
        capitale_iniziale=_get_env_float("CAPITALE_INIZIALE", 100000.0),
        investimento_per_trade=_get_env_float("INVESTIMENTO_PER_TRADE", 10000.0),
        commissione_apertura=_get_env_float("COMMISSIONE_APERTURA", 10.0),
        commissione_chiusura=_get_env_float("COMMISSIONE_CHIUSURA", 10.0),
        window_profile=_get_env_int("WINDOW_PROFILE", 25),
        price_tolerance=_get_env_float("PRICE_TOLERANCE", 0.05),
        lvn_threshold=_get_env_float("LVN_THRESHOLD", 0.50),
        bin_step=_get_env_float("BIN_STEP", 0.05),
        min_profile_levels=_get_env_int("MIN_PROFILE_LEVELS", 5),
    )

    runtime = RuntimeConfig(
        data_dir=_get_env_str("DATA_DIR", "data"),
        database_dir=_get_env_str("DATABASE_DIR", "database"),
        request_timeout=_get_env_int("REQUEST_TIMEOUT", 10),
        max_retries=_get_env_int("MAX_RETRIES", 3),
        retry_sleep_seconds=_get_env_int("RETRY_SLEEP_SECONDS", 2),
    )

    log_level = _get_env_str("LOG_LEVEL", "INFO")
    log_dir = _get_env_str("LOG_DIR", "logs")
    log_file = _normalize_log_file(log_dir, _get_env_str("LOG_FILE", ""))

    logging_cfg = LoggingConfig(
        log_level=log_level,
        log_dir=log_dir,
        log_file=log_file,
    )

    _validate_secret_config(secrets)
    _validate_strategy_config(strategy)
    _validate_runtime_config(runtime)
    _validate_logging_config(logging_cfg)

    return AppConfig(
        secrets=secrets,
        strategy=strategy,
        runtime=runtime,
        logging=logging_cfg,
    )


CONFIG = load_config()
from config_Version6 import *  # noqa: F401,F403
