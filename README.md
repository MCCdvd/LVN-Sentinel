# LVN-Sentinel

LVN Sentinel is a small trading workflow that downloads OHLCV data, scans for LVN-based signals, updates a CSV portfolio, and sends Telegram alerts.

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Install the Python dependencies used by the project:
   - `python-dotenv`
   - `pandas`
   - `numpy`
   - `scipy`
   - `yfinance`
   - `requests`
   - `matplotlib` (optional: enables the 5-day trend chart image in Telegram; without it a text trend is used)

`DATA_DIR`, `DATABASE_DIR`, and `LOG_DIR` are created automatically on first run. If `LOG_FILE` is left empty, the app writes logs to `LOG_DIR/app.log`.

## Usage

Run the sentinel from the repository root:

```bash
python main.py
```

## Daily P&L report

Each run sends the Telegram report `LVN Sentinel Report - rev 031026` with daily realized P&L, unrealized P&L of open positions, `Total P&L from first day run` and a 5-day trend (text, plus a PNG chart when `matplotlib` is installed).

- Realized P&L comes from `DATABASE_DIR/history.csv` (closed events).
- Unrealized P&L is computed from open positions in `DATABASE_DIR/portfolio.csv`; if today's price is missing, the last known price (`last_price`) is used and the ticker is flagged in the report.
- A daily snapshot is stored in `DATABASE_DIR/daily_pnl.csv` (one row per day; repeated runs on the same day overwrite that day's row, so nothing is double-counted).
