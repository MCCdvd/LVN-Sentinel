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

`DATA_DIR`, `DATABASE_DIR`, and `LOG_DIR` are created automatically on first run. If `LOG_FILE` is left empty, the app writes logs to `LOG_DIR/app.log`.

## Usage

Run the sentinel from the repository root:

```bash
python main.py
```
