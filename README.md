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

## Versione RSI

La branch `RSI` introduce una variante della strategia LVN con filtro RSI sui segnali di ingresso.

### Obiettivo
- ridurre gli ingressi di bassa qualità
- mantenere invariata la gestione delle posizioni già esistente
- rendere coerenti live e backtest con la stessa logica di filtro

### Regole RSI
- timeframe: **daily close**
- periodo: **14**
- **LONG** consentito solo se `RSI <= 35`
- **SHORT** consentito solo se `RSI >= 65`
- se il filtro RSI non passa, il segnale diventa `WAIT`

### Cosa resta invariato
- calcolo LVN
- hard stop loss
- TP1
- trailing stop
- formato CSV di output
- flusso di portafoglio e report

### File coinvolti
- `config.py` → soglie RSI configurabili
- `engine.py` → filtro RSI nella generazione segnali
- `backtest.py` → filtro RSI nel backtest
