import engine_Version2 as _impl
from engine_Version2 import *  # noqa: F401,F403


def run_scanner() -> _impl.List[_impl.Dict]:
    if not _impl.os.path.exists(_impl.CONFIG.runtime.data_dir):
        return []

    results = []

    for file in sorted(_impl.os.listdir(_impl.CONFIG.runtime.data_dir)):
        if not file.endswith(".csv") or file == "failed_tickers.csv":
            continue

        ticker = file.replace(".csv", "")

        try:
            res = _impl.analyze_ticker(ticker)
            if res:
                results.append(res)
        except Exception as e:
            _impl.logger.exception("Errore analisi ticker %s", ticker)
            results.append({
                "ticker": ticker,
                "date": None,
                "price": None,
                "lvn": None,
                "signal": "ERROR",
                "reason": str(e)
            })

    return results
