# XECUTE

Personal automated options trading bot. Single VPS, IBKR brokerage, Discord channel signals + autonomous scanner, mandatory pre-trade technical analysis filter, Unusual Whales flow integration.

> Work in progress. Each step ships as a checkpoint with tests.

## Account & sizing

- **IBKR account base currency:** CAD
- **Starting USD budget:** ~$290 (400 CAD converted manually on IBKR — bot does NOT trade FX)
- **Risk caps:** per-trade $100, daily loss limit -$150 (kill switch trips here), max 2 concurrent positions, hard cap 3 contracts/order
- **Scanner:** enabled with 1 trade/day cap; Discord is the primary source
- **Trading mode:** LIVE in production. PAPER retained as a dev/test target you can point the executor at to validate parser/analysis/scanner changes without real fills (shadow mode was dropped — wasn't worth the complexity for a single-account deployment).

## Status

| Step | What | State |
|------|------|-------|
| 1 | Repo scaffold, shared models, SQLite schema, config loader | ✅ |
| 1b | Budget/mode refactor (live-default, tight caps, shadow dropped) | ✅ |
| 2 | Discord signal parser + 30+ message test suite | ✅ |
| 3 | IBKR connection module + paper integration test | 🟡 in progress |
| 4 | Pre-trade analysis module + unit tests | ⏳ |
| 5 | Unusual Whales client + tests | ⏳ |
| 6 | Pipeline integration: Discord → analysis → executor → paper fill | ⏳ |
| 7 | Risk engine + tests + pipeline | ⏳ |
| 8 | Mode toggle (PAPER ↔ LIVE; no shadow) | ⏳ |
| 9 | Scanner: ORB strategy, scheduler, watchlist (1 trade/day cap) | ⏳ |
| 10 | Dashboard | ⏳ |
| 11 | systemd + VPS provisioning + README finalisation | ⏳ |
| 12 | End-to-end smoke on staging VPS | ⏳ |

## Layout

```
app/
  listener/    Discord listener + raw signal ingestion
  parser/      regex + LLM signal parsing
  scanner/     autonomous signal generation (ORB)
  analysis/    pre-trade technical analysis + UW flow filter
  risk/        risk engine
  executor/    IB connection mgmt + order placement
  dashboard/   FastAPI + htmx UI
  shared/      pydantic models, enums, config, sqlite utils
tests/
systemd/       service files
scripts/       VPS provisioning + IB smoke tests
```

## Local quickstart (dev)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # leave LIVE_TRADING_ENABLED=false
python -c "from app.shared.db import init_db; print(init_db())"
pytest
```

Full IBKR / Discord / Unusual Whales / VPS setup docs land at Step 11.
