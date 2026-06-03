# XECUTE

Personal automated options trading bot. Single VPS, IBKR brokerage. Fully autonomous: pulls market data + news + sentiment + Unusual Whales flow, generates and executes call-option trades against the same mandatory pre-trade analysis filter that gates every order.

> Work in progress. Each step ships as a checkpoint with tests.

## Account & sizing

- **IBKR account base currency:** CAD
- **Starting USD budget:** ~$290 (400 CAD converted manually on IBKR — bot does NOT trade FX)
- **Risk caps:** per-trade $100, daily loss limit −$150 (kill switch trips here), max 2 concurrent positions, hard cap 3 contracts/order, **hard global cap of 3 trades/day across all sources**
- **Trading mode:** LIVE in production (gated by `LIVE_TRADING_ENABLED=true`). PAPER retained as a dev/test target you can point the executor at to validate changes without real fills.

## Signal sources (all flow through the same pre-trade analysis + risk + executor pipeline)

1. **Autonomous scanner** with pluggable strategies:
   - **ORB** — opening-range breakout on a configurable watchlist
   - **News-momentum** — Polygon news + Claude Haiku 4.5 sentiment + UW flow alignment
   - **LLM-suggest** — Claude picks ATM strikes from the watchlist given current market state, news, and flow. Auto-executes.
2. **Manual paste** — dashboard textbox you drop signal-channel messages into. Channel format (M/D optional, missing date = 0DTE):
   ```
   META 630C @1.00
   MSFT 462.50C @1.45
   MS 210C @2.25 05/06
   ```

## Status

| Step | What | State |
|------|------|-------|
| 1 | Repo scaffold, shared models, SQLite schema, config loader | ✅ |
| 1b | Budget/mode refactor (live-default, tight caps, shadow dropped) | ✅ |
| 2 | Signal parser + 30+ message test suite | ✅ |
| 3 | IBKR connection module + paper integration test | ✅ |
| 3b | Spec lock-in: Polygon news, LLM-suggest, 3/day cap, channel format flag | ✅ |
| 4 | Pre-trade analysis module (trend / VWAP / volume / RSI / ATR / liquidity / flow) | 🟡 next |
| 5 | Unusual Whales client + tests | ⏳ |
| 5b | Polygon.io client (news + market data + option chains) | ⏳ |
| 5c | Sentiment analyzer (Claude Haiku 4.5, structured JSON) | ⏳ |
| 6 | Pipeline integration: signal → analysis → executor → fill | ⏳ |
| 7 | Risk engine + tests + pipeline (incl. 3/day total cap) | ⏳ |
| 8 | Mode toggle (PAPER ↔ LIVE; no shadow) | ⏳ |
| 9 | Scanner: ORB + News-momentum + LLM-suggest strategies | ⏳ |
| 10 | Dashboard (incl. manual paste box, LLM suggestions panel) | ⏳ |
| 11 | systemd + VPS provisioning + README finalisation | ⏳ |
| 12 | End-to-end smoke on staging VPS | ⏳ |

## Layout

```
app/
  listener/    Manual-paste endpoint + raw signal ingestion
  parser/      regex + LLM signal parsing (channel-format aware)
  scanner/     ORB / News-momentum / LLM-suggest strategies
  analysis/    Pre-trade technical analysis + UW flow filter + sentiment
  risk/        Risk engine (per-source caps + 3/day global cap)
  executor/    IB connection + order placement
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

External services needed before going live:
- IBKR account with options permissions + IB Gateway running on the VPS (paper port 4002, live port 4001)
- Discord-channel paste workflow (manual; no bot ingestion)
- Anthropic API key (Claude Haiku 4.5 — used by parser fallback, sentiment, LLM-suggest)
- Unusual Whales API key
- Polygon.io Stocks Starter ($29/mo) for news + market data

Full setup docs land at Step 11.
