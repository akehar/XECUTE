# XECUTE

Personal automated options trading bot. Single VPS, IBKR brokerage, two signal sources (Discord channel + autonomous scanner), mandatory pre-trade technical analysis filter, Unusual Whales flow integration.

> Work in progress. See `BUILD_ORDER` in the original spec — each step ships as a checkpoint with tests.

## Status

| Step | What | State |
|------|------|-------|
| 1 | Repo scaffold, shared models, SQLite schema, config loader | ✅ in progress / under review |
| 2 | Discord signal parser + 30+ message test suite | ⏳ |
| 3 | IBKR connection module + paper integration test | ⏳ |
| 4 | Pre-trade analysis module + unit tests | ⏳ |
| 5 | Unusual Whales client + tests | ⏳ |
| 6 | Pipeline integration: Discord → analysis → executor → paper fill | ⏳ |
| 7 | Risk engine + tests + pipeline | ⏳ |
| 8 | Mode system: dual-connection executor, shadow mode | ⏳ |
| 9 | Scanner: ORB strategy, scheduler, watchlist | ⏳ |
| 10 | Dashboard | ⏳ |
| 11 | systemd + VPS provisioning + README finalisation | ⏳ |
| 12 | End-to-end smoke on staging VPS | ⏳ |

## Layout

```
app/
  listener/    Discord listener + raw signal ingestion
  parser/      regex + LLM signal parsing
  scanner/     autonomous signal generation
  analysis/    pre-trade technical analysis + UW flow filter
  risk/        risk engine
  executor/    IB connection mgmt, order placement, dual-mode switching
  dashboard/   FastAPI + htmx UI
  shared/      pydantic models, enums, config, sqlite utils
tests/
systemd/       service files
scripts/       VPS provisioning
```

## Local quickstart (dev only — no real money)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # leave LIVE_TRADING_ENABLED=false
python -c "from app.shared.db import init_db; print(init_db())"
pytest
```

Full IBKR / Discord / Unusual Whales / VPS setup docs land at Step 11.
