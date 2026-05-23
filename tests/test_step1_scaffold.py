"""Step 1 smoke tests: shared models validate, DB schema initializes, config loads."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.shared.config import Settings
from app.shared.db import init_db
from app.shared.enums import (
    FlowVerdict,
    Mode,
    OptionRight,
    OrderStatus,
    SignalAction,
    SignalSource,
    SignalStatus,
)
from app.shared.ids import new_signal_id
from app.shared.models import (
    AnalysisReport,
    CheckResult,
    FlowData,
    ModeState,
    OrderResult,
    PipelineOutcome,
    RiskDecision,
    Signal,
)


def _good_signal(**overrides) -> Signal:
    base = dict(
        source=SignalSource.DISCORD,
        action=SignalAction.BTO,
        ticker="spy",
        strike=500.0,
        right=OptionRight.CALL,
        expiry=date.today() + timedelta(days=7),
        price=2.50,
        raw_text="BTO SPY 500c exp +7d @ 2.50",
        parse_confidence=0.97,
    )
    base.update(overrides)
    return Signal(**base)


class TestSignalModel:
    def test_valid_signal_normalizes_ticker(self):
        s = _good_signal(ticker="spy")
        assert s.ticker == "SPY"
        assert s.action == SignalAction.BTO
        assert s.right == OptionRight.CALL

    def test_rejects_negative_strike(self):
        with pytest.raises(ValidationError):
            _good_signal(strike=-1.0)

    def test_rejects_zero_price(self):
        with pytest.raises(ValidationError):
            _good_signal(price=0.0)

    def test_rejects_past_expiry(self):
        with pytest.raises(ValidationError):
            _good_signal(expiry=date.today() - timedelta(days=1))

    def test_rejects_expiry_beyond_60_days(self):
        with pytest.raises(ValidationError):
            _good_signal(expiry=date.today() + timedelta(days=61))

    def test_accepts_expiry_at_boundary(self):
        s = _good_signal(expiry=date.today() + timedelta(days=60))
        assert (s.expiry - date.today()).days == 60

    def test_id_assignable(self):
        s = _good_signal()
        s.id = new_signal_id()
        assert s.id.startswith("sig_")


class TestAnalysisReport:
    def test_failing_checks_extracted(self):
        checks = [
            CheckResult(name="trend", passed=True, reason="ok"),
            CheckResult(name="vwap", passed=False, reason="below vwap"),
            CheckResult(name="rsi", passed=False, reason="rsi 85"),
        ]
        r = AnalysisReport(overall_pass=False, checks=checks, flow_verdict=FlowVerdict.NEUTRAL)
        names = [c.name for c in r.failing_checks()]
        assert names == ["vwap", "rsi"]


class TestOrderResult:
    def test_is_filled_property(self):
        o = OrderResult(mode=Mode.PAPER, status=OrderStatus.FILLED, contracts_filled=2)
        assert o.is_filled

    def test_pending_not_filled(self):
        o = OrderResult(mode=Mode.PAPER, status=OrderStatus.PENDING)
        assert not o.is_filled


class TestFlowAndRisk:
    def test_flow_data_defaults(self):
        f = FlowData(ticker="SPY", window_minutes=30)
        assert f.verdict == FlowVerdict.NEUTRAL
        assert f.net_premium == 0.0

    def test_risk_decision_default_accepted(self):
        d = RiskDecision(accepted=True)
        assert d.accepted
        assert d.reason == ""


class TestModeState:
    def test_default_paper(self):
        m = ModeState()
        assert m.mode == Mode.PAPER
        assert not m.confirmation_phrase_ok


class TestPipelineOutcome:
    def test_holds_full_pipeline(self):
        sig = _good_signal()
        sig.id = new_signal_id()
        report = AnalysisReport(
            signal_id=sig.id, overall_pass=True, checks=[], flow_verdict=FlowVerdict.BULLISH
        )
        outcome = PipelineOutcome(signal=sig, status=SignalStatus.FILLED, analysis=report)
        assert outcome.status == SignalStatus.FILLED
        assert outcome.analysis.overall_pass


class TestConfig:
    def test_settings_load_with_defaults(self, monkeypatch, tmp_path: Path):
        # Force a no-env load
        monkeypatch.chdir(tmp_path)
        s = Settings(_env_file=None)
        assert s.live_trading_enabled is False
        assert s.parse_min_confidence == 0.85
        assert s.daily_loss_limit == -500.0
        assert s.flow_fail_mode == "inconclusive_passes"

    def test_watchlist_parsed(self, monkeypatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        s = Settings(_env_file=None, scanner_watchlist="spy, qqq ,aapl")
        assert s.watchlist == ["SPY", "QQQ", "AAPL"]

    def test_channel_id_list(self, monkeypatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        s = Settings(_env_file=None, discord_channel_ids="123,456,789")
        assert s.channel_id_list == [123, 456, 789]

    def test_channel_id_list_empty(self, monkeypatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        s = Settings(_env_file=None)
        assert s.channel_id_list == []

    def test_invalid_flow_fail_mode_rejected(self, monkeypatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValidationError):
            Settings(_env_file=None, flow_fail_mode="explode")


class TestDB:
    def test_init_db_creates_tables(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        result = init_db(db_path)
        assert result.exists()

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        table_names = {r[0] for r in rows}
        expected = {
            "signals",
            "analysis_reports",
            "analysis_checks",
            "risk_decisions",
            "orders",
            "positions",
            "mode_state",
            "kill_switch",
            "scanner_state",
            "config_overrides",
            "logs",
            "shadow_pairs",
        }
        assert expected.issubset(table_names), f"missing: {expected - table_names}"

    def test_init_db_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        init_db(db_path)  # second call must not raise
        with sqlite3.connect(db_path) as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM mode_state").fetchone()
        assert count == 1

    def test_default_mode_paper(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT mode, shadow_enabled FROM mode_state WHERE id=1").fetchone()
        assert row[0] == "PAPER"
        assert row[1] == 0

    def test_kill_switch_default_off(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT engaged FROM kill_switch WHERE id=1").fetchone()
        assert row[0] == 0


class TestEnumsRoundTrip:
    def test_signal_status_values(self):
        assert SignalStatus.REJECTED_BY_ANALYSIS.value == "rejected_by_analysis"
        assert SignalStatus.REJECTED_BY_RISK.value == "rejected_by_risk"

    def test_mode_values(self):
        assert Mode.LIVE_WITH_SHADOW.value == "LIVE_WITH_SHADOW"
