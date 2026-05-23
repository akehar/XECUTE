from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.shared.config import get_settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS signals (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,                  -- discord | scanner
    action          TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    strike          REAL NOT NULL,
    right           TEXT NOT NULL,                  -- C | P
    expiry          TEXT NOT NULL,                  -- ISO date
    price           REAL NOT NULL,
    stop            REAL,
    target          REAL,
    raw_text        TEXT,
    parse_confidence REAL,
    status          TEXT NOT NULL,                  -- SignalStatus
    received_at     TEXT NOT NULL,
    meta_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_received ON signals(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_dedup ON signals(ticker, strike, expiry, right, source, received_at);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id       TEXT NOT NULL,
    overall_pass    INTEGER NOT NULL,
    flow_verdict    TEXT NOT NULL,
    indicators_json TEXT,
    generated_at    TEXT NOT NULL,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);
CREATE INDEX IF NOT EXISTS idx_analysis_signal ON analysis_reports(signal_id);

CREATE TABLE IF NOT EXISTS analysis_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id       INTEGER NOT NULL,
    name            TEXT NOT NULL,
    passed          INTEGER NOT NULL,
    reason          TEXT NOT NULL,
    value           TEXT,
    threshold       TEXT,
    FOREIGN KEY(report_id) REFERENCES analysis_reports(id)
);
CREATE INDEX IF NOT EXISTS idx_checks_report ON analysis_checks(report_id);
CREATE INDEX IF NOT EXISTS idx_checks_name ON analysis_checks(name, passed);

CREATE TABLE IF NOT EXISTS risk_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id       TEXT NOT NULL,
    accepted        INTEGER NOT NULL,
    rule            TEXT,
    reason          TEXT,
    snapshot_json   TEXT,
    decided_at      TEXT NOT NULL,
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);
CREATE INDEX IF NOT EXISTS idx_risk_signal ON risk_decisions(signal_id);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id       TEXT,
    mode            TEXT NOT NULL,                  -- PAPER | LIVE
    status          TEXT NOT NULL,
    ib_order_id     INTEGER,
    ib_perm_id      INTEGER,
    contracts_requested INTEGER,
    contracts_filled INTEGER,
    avg_fill_price  REAL,
    limit_price     REAL,
    submitted_at    TEXT,
    filled_at       TEXT,
    error           TEXT,
    shadow_of       INTEGER,                        -- references orders.id when shadow paper-mirror of a live order
    FOREIGN KEY(signal_id) REFERENCES signals(id),
    FOREIGN KEY(shadow_of) REFERENCES orders(id)
);
CREATE INDEX IF NOT EXISTS idx_orders_signal ON orders(signal_id);
CREATE INDEX IF NOT EXISTS idx_orders_mode ON orders(mode, submitted_at DESC);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mode            TEXT NOT NULL,                  -- PAPER | LIVE
    ticker          TEXT NOT NULL,
    strike          REAL NOT NULL,
    right           TEXT NOT NULL,
    expiry          TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    avg_cost        REAL NOT NULL,
    opened_by_bot   INTEGER NOT NULL DEFAULT 1,
    opened_at       TEXT NOT NULL,
    closed_at       TEXT,
    realized_pnl    REAL,
    source          TEXT,                           -- signal source that opened it
    opening_order_id INTEGER,
    FOREIGN KEY(opening_order_id) REFERENCES orders(id)
);
CREATE INDEX IF NOT EXISTS idx_positions_open ON positions(mode, closed_at);
CREATE INDEX IF NOT EXISTS idx_positions_contract ON positions(ticker, strike, expiry, right, mode);

CREATE TABLE IF NOT EXISTS mode_state (
    id                      INTEGER PRIMARY KEY CHECK (id = 1),
    mode                    TEXT NOT NULL DEFAULT 'PAPER',
    confirmation_phrase_ok  INTEGER NOT NULL DEFAULT 0,
    shadow_enabled          INTEGER NOT NULL DEFAULT 0,
    updated_at              TEXT NOT NULL
);
INSERT OR IGNORE INTO mode_state (id, mode, confirmation_phrase_ok, shadow_enabled, updated_at)
VALUES (1, 'PAPER', 0, 0, datetime('now'));

CREATE TABLE IF NOT EXISTS kill_switch (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    engaged     INTEGER NOT NULL DEFAULT 0,
    reason      TEXT,
    engaged_at  TEXT
);
INSERT OR IGNORE INTO kill_switch (id, engaged) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS scanner_state (
    ticker          TEXT NOT NULL,
    trade_date      TEXT NOT NULL,                  -- YYYY-MM-DD ET
    or_high         REAL,
    or_low          REAL,
    or_established  INTEGER NOT NULL DEFAULT 0,
    setup_taken     TEXT,                           -- 'call' | 'put' | NULL
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (ticker, trade_date)
);

CREATE TABLE IF NOT EXISTS config_overrides (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    level       TEXT NOT NULL,
    module      TEXT NOT NULL,
    message     TEXT NOT NULL,
    context_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_logs_module ON logs(module, ts DESC);

CREATE TABLE IF NOT EXISTS shadow_pairs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    live_order_id   INTEGER NOT NULL,
    paper_order_id  INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY(live_order_id) REFERENCES orders(id),
    FOREIGN KEY(paper_order_id) REFERENCES orders(id)
);
CREATE INDEX IF NOT EXISTS idx_shadow_pairs_live ON shadow_pairs(live_order_id);
"""


def init_db(path: str | Path | None = None) -> Path:
    """Create the DB file and tables if they don't exist. Returns the resolved path."""
    if path is None:
        db_path = get_settings().db_path_abs
    else:
        db_path = Path(path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return db_path


@contextmanager
def connect(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    if path is None:
        db_path = get_settings().db_path_abs
    else:
        db_path = Path(path).resolve()
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit; use BEGIN explicitly when needed
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()
