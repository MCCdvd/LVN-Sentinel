# LVN Single Ticker Analysis

Workspace standalone per ottimizzare e validare parametri LVN **su ciascun titolo**.

## Obiettivo

- trovare parametri migliori ticker-by-ticker
- salvare output separati per ogni ticker
- confrontare il risultato con una baseline globale a parametri condivisi

## Moduli minimi

- `config.py`: default runtime/strategia/grid
- `engine.py`: logica segnali LVN + filtro RSI
- `backtest.py`: backtest per singolo ticker
- `optimizer.py`: ottimizzazione per ticker + confronto baseline

## Flusso CLI

1. Backtest singolo ticker

```bash
python /home/runner/work/LVN-Sentinel/LVN-Sentinel/single_ticker_analysis/backtest.py --ticker UCG
```

2. Ottimizzazione per ticker + confronto globale

```bash
python /home/runner/work/LVN-Sentinel/LVN-Sentinel/single_ticker_analysis/optimizer.py
```

## Struttura output

Output base: `database/single_ticker_analysis/`

- `baseline_global/`
  - `params.csv`
  - `trades.csv`
  - `summary_by_ticker.csv`
  - `summary_global.csv`
- `per_ticker/<TICKER>/`
  - `results.csv`
  - `ranking.csv`
  - `best_params.csv`
- `per_ticker_best_global/`
  - `best_params_all_tickers.csv`
  - `trades.csv`
  - `summary_by_ticker.csv`
  - `summary_global.csv`
- `comparison_baseline_vs_per_ticker.csv`

