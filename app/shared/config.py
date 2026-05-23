from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed config. Use get_settings() rather than instantiating directly."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Mode locks
    live_trading_enabled: bool = False

    # IBKR
    ibkr_paper_host: str = "127.0.0.1"
    ibkr_paper_port: int = 4002
    ibkr_paper_client_id: int = 11
    ibkr_live_host: str = "127.0.0.1"
    ibkr_live_port: int = 4001
    ibkr_live_client_id: int = 12

    # Discord
    discord_bot_token: str = ""
    discord_channel_ids: str = ""  # comma-separated; parsed via channel_id_list

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"

    # Unusual Whales
    uw_api_key: str = ""
    uw_base_url: str = "https://api.unusualwhales.com"
    flow_fail_mode: str = "inconclusive_passes"  # inconclusive_passes | fail_closed

    # Parser
    parse_min_confidence: float = 0.85

    # Risk
    trading_hours_start: str = "09:35"
    trading_hours_end: str = "15:55"
    daily_loss_limit: float = -500.0
    max_concurrent_positions: int = 5
    per_trade_dollar_cap: float = 500.0
    hard_contract_cap: int = 10
    orders_per_hour: int = 20
    slippage_tolerance: float = 0.02
    duplicate_window_seconds: int = 60

    # Scanner
    scanner_enabled: bool = True
    scanner_watchlist: str = "SPY,QQQ,AAPL,TSLA,NVDA,AMD,MSFT,META,AMZN,GOOGL"
    scanner_daily_trade_cap: int | None = None

    # Pre-trade analysis toggles (defaults all ON; live toggles also live in config_overrides table)
    check_trend: bool = True
    check_vwap: bool = True
    check_volume: bool = True
    check_rsi: bool = True
    check_atr: bool = True
    check_liquidity: bool = True
    check_flow: bool = True

    # Dashboard
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8080

    # Storage
    db_path: str = "./data/xecute.db"
    log_dir: str = "./logs"

    # Dev
    dry_run: bool = False

    @field_validator("flow_fail_mode")
    @classmethod
    def _valid_flow_mode(cls, v: str) -> str:
        if v not in {"inconclusive_passes", "fail_closed"}:
            raise ValueError("flow_fail_mode must be inconclusive_passes or fail_closed")
        return v

    @property
    def channel_id_list(self) -> list[int]:
        if not self.discord_channel_ids:
            return []
        return [int(x) for x in self.discord_channel_ids.split(",") if x.strip()]

    @property
    def watchlist(self) -> list[str]:
        return [t.strip().upper() for t in self.scanner_watchlist.split(",") if t.strip()]

    @property
    def db_path_abs(self) -> Path:
        return Path(self.db_path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Tests can clear the cache after monkeypatching env vars."""
    get_settings.cache_clear()
