# Progetto LVN Sentinel — checkpoint operativo

> Obiettivo: mantenere uno stato persistente del lavoro, con priorità, problemi noti, decisioni tecniche e prossimi passi, così da poter riprendere facilmente dopo un’interruzione.

## 1. Stato attuale del progetto

Il progetto è un sistema di scanning LVN (Low Volume Node) per azioni europee, con:
- aggiornamento dati via Yahoo Finance
- scansione segnali LONG/SHORT
- gestione portafoglio con TP1 e trailing stop
- notifiche Telegram
- logging locale
- ottimizzazione parametri tramite backtest

L’architettura è già divisa in moduli, ma ci sono ancora incoerenze tra strategia live e strategia di backtest, oltre a diverse fragilità operative.

## 2. File principali e ruolo

- `config.py` → carica e centralizza la configurazione da `.env`
- `data_manager.py` → scarica e aggiorna i dati storici dei ticker
- `engine.py` → calcola LVN e genera segnali
- `portfolio_manager.py` → apre/aggiorna posizioni e calcola report
- `brain_optimizer.py` → esegue ottimizzazione parametri e backtest
- `main_Version5.py` → orchestrazione del flusso principale
- `logging_setup.py` → configurazione logging

## 3. Punti critici già individuati

### Sicurezza
- [ ] Il file `.env` condiviso in chat conteneva un token Telegram reale.
- [ ] Il token va revocato e rigenerato immediatamente.
- [ ] Il repository deve usare `.env.example` senza segreti.

### Coerenza tecnica
- [ ] La logica live in `engine.py` e la logica di backtest in `brain_optimizer.py` non sono allineate.
- [ ] Alcuni parametri di strategia sono duplicati o hardcoded in punti diversi.
- [ ] TP1 e trailing stop hanno soglie diverse tra backtest e runtime.

### Robustezza
- [ ] La persistenza su CSV è semplice ma fragile.
- [ ] Mancano test automatici.
- [ ] La gestione degli errori su dati scaricati e file corrotti può essere migliorata.
- [ ] Il retry usa un valore hardcoded invece di `CONFIG.retry_sleep_seconds`.

### Manutenibilità
- [ ] `main_Version5.py` ha un nome provvisorio e dovrebbe diventare `main.py`.
- [ ] Il README va ripulito e reso più leggibile.
- [ ] La logica di volume profile / LVN andrebbe centralizzata.

## 4. Cose già buone

- [x] Configurazione centralizzata via `config.py`
- [x] Logging già presente
- [x] Separazione in moduli distinti
- [x] Gestione semplice e comprensibile dei dati
- [x] Presenza di un optimizer per testare i parametri

## 5. Problemi prioritari da risolvere

### Priorità alta
- [ ] Revocare il token Telegram esposto
- [ ] Allineare la logica live con il backtest
- [ ] Eliminare parametri hardcoded e usare un’unica fonte di configurazione
- [ ] Usare il retry sleep da configurazione
- [ ] Verificare che tutti i moduli importati esistano davvero

### Priorità media
- [ ] Rinominare `main_Version5.py` in `main.py`
- [ ] Ripulire `README.md`
- [ ] Migliorare validazione e parsing dei CSV
- [ ] Rendere più robusto il portafoglio su casi limite

### Priorità bassa ma utile
- [ ] Migrazione da CSV a SQLite
- [ ] Aggiunta di test unitari e test di integrazione
- [ ] Walk-forward analysis per validare la strategia
- [ ] Parallelizzazione dell’optimizer se i ticker diventano molti

## 6. Decisioni tecniche consigliate

### Strategia
- Una sola implementazione della logica LVN deve essere condivisa tra runtime e backtest.
- La definizione di “touch LVN” deve essere esplicitata e resa consistente.
- Va chiarito se la strategia è mean reversion, breakout, o una combinazione delle due.

### Architettura
- Tenere la logica di calcolo separata da I/O e persistenza.
- Evitare duplicazioni di funzione tra `engine.py` e `brain_optimizer.py`.
- Valutare una classe/servizio dedicato al volume profile.

### Persistenza
- CSV ok per prototipo, ma fragile per esecuzione continua.
- Se il progetto cresce, migrare a SQLite o a uno storage con locking.

### Operatività
- Mettere i segreti fuori dal repository.
- Aggiungere logging più strutturato per diagnosi.
- Introdurre test sui percorsi critici.

## 7. Roadmap operativa

### Fase 1 — Sicurezza e coerenza
- [ ] Revocare e rigenerare il token Telegram
- [ ] Creare `.env.example` pulito
- [ ] Allineare runtime e backtest
- [ ] Centralizzare i parametri della strategia

### Fase 2 — Refactor mirato
- [ ] Rinominare il file di entrypoint in `main.py`
- [ ] Estrarre la logica LVN comune
- [ ] Eliminare duplicazioni
- [ ] Ripulire la gestione dei retry

### Fase 3 — Stabilità operativa
- [ ] Rafforzare lettura/scrittura CSV
- [ ] Aggiungere test automatici
- [ ] Migliorare gestione errori e logging
- [ ] Valutare migrazione a SQLite

### Fase 4 — Evoluzione strategica
- [ ] Definire meglio i criteri di segnale
- [ ] Introdurre conferme di entrata
- [ ] Fare walk-forward analysis
- [ ] Valutare metriche aggiuntive oltre al profit factor

## 8. Ordine consigliato di analisi dei file

1. `config.py`
2. `data_manager.py`
3. `engine.py`
4. `portfolio_manager.py`
5. `brain_optimizer.py`
6. `main_Version5.py`
7. `logging_setup.py`

## 9. Criteri di completamento per il checkpoint

Questo file è utile se:
- permette di riprendere il lavoro senza ricostruire il contesto
- evidenzia i problemi già trovati
- contiene una roadmap pratica
- mantiene l’ordine dei prossimi interventi

## 10. Prossimo step consigliato

- [ ] Revisione dettagliata di `config.py`
- [ ] Creazione di `.env.example` senza segreti
- [ ] Allineamento tra strategia live e backtest

## 11. Note aperte

- Verificare se esiste già `telegram_manager.py` nel repository.
- Verificare se il progetto ha un entrypoint definitivo.
- Verificare se ci sono script di deploy o test non ancora condivisi.
