from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PAPER_TRADING_ORIGIN = "https://paper-api.alpaca.markets"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Environment-only configuration with non-negotiable paper-trading guards."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SignalForge API"
    app_environment: Environment = Environment.DEVELOPMENT
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    database_url: str = "postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge"
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout_seconds: float = 10.0
    database_transaction_pooler: bool = False

    alpaca_trading_base_url: str = PAPER_TRADING_ORIGIN
    alpaca_data_base_url: str = "https://data.alpaca.markets"
    alpaca_api_key: SecretStr | None = Field(default=None, repr=False)
    alpaca_secret_key: SecretStr | None = Field(default=None, repr=False)
    alpaca_live_trade: bool = False
    order_submission_enabled: bool = False
    alpaca_request_timeout_seconds: float = 15.0
    alpaca_max_safe_retries: int = 3
    alpaca_retry_base_seconds: float = 0.25
    alpaca_stock_feed: str = "iex"
    alpaca_option_feed: str = "indicative"

    openai_api_key: SecretStr | None = Field(default=None, repr=False)
    openai_model: str = "gpt-5-mini"
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    openai_request_timeout_seconds: float = 30.0
    openai_max_retries: int = 1
    openai_max_input_chars: int = 12_000

    market_watchlist: str = (
        "SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMD,TSLA,META,AMZN,GOOGL,"
        "NFLX,AVGO,JPM,BAC,XOM,COIN,PLTR,INTC,TLT"
    )
    market_scan_lookback_days: int = 180
    market_max_data_age_seconds: int = 345_600
    opportunity_signal_threshold: Decimal = Decimal("0.35")
    opportunity_min_volume_ratio: Decimal = Decimal("0.75")

    risk_max_risk_per_trade_pct: Decimal = Decimal("0.0075")
    risk_max_premium_per_trade: Decimal = Decimal("750")
    risk_max_portfolio_exposure_pct: Decimal = Decimal("0.05")
    risk_max_open_positions: int = 4
    risk_max_underlying_exposure_pct: Decimal = Decimal("0.015")
    risk_min_ai_confidence: Decimal = Decimal("0.72")
    risk_max_daily_loss_pct: Decimal = Decimal("0.02")
    risk_max_consecutive_losses: int = 3
    risk_cooldown_minutes: int = 30
    risk_max_quote_age_seconds: int = 15
    risk_min_volume_ratio: Decimal = Decimal("0.75")
    risk_max_bid_ask_spread_pct: Decimal = Decimal("0.15")
    risk_min_dte: int = 7
    risk_max_dte: int = 35
    risk_kill_switch: bool = False

    option_target_dte: int = 21
    option_max_strike_distance_pct: Decimal = Decimal("0.10")
    option_min_bid_size: Decimal = Decimal("1")
    option_min_ask_size: Decimal = Decimal("1")

    exit_stop_loss_pct: Decimal = Decimal("0.35")
    exit_take_profit_pct: Decimal = Decimal("0.60")
    exit_max_holding_days: int = 10
    exit_dte: int = 2

    agent_scan_interval_seconds: int = 300
    agent_autonomy_enabled: bool = False
    demo_mode: bool = False
    control_api_token: SecretStr | None = Field(default=None, repr=False)
    alpaca_cli_executable: str = "alpaca"
    alpaca_cli_timeout_seconds: float = 10.0

    @model_validator(mode="after")
    def enforce_safety_invariants(self) -> Self:
        trading_url = self.alpaca_trading_base_url.rstrip("/").lower()
        parsed = urlparse(trading_url)
        if self.alpaca_live_trade:
            raise ValueError("ALPACA_LIVE_TRADE is forbidden; SignalForge is paper-only")
        if trading_url != PAPER_TRADING_ORIGIN:
            raise ValueError("ALPACA_TRADING_BASE_URL must be the exact Alpaca paper endpoint")
        if parsed.scheme != "https" or parsed.hostname != "paper-api.alpaca.markets":
            raise ValueError("Alpaca trading endpoint failed the paper-only allowlist")
        api_key_set = self._secret_is_set(self.alpaca_api_key)
        secret_key_set = self._secret_is_set(self.alpaca_secret_key)
        if api_key_set != secret_key_set:
            raise ValueError("Alpaca API key and secret must be configured together")
        if self.order_submission_enabled and not (api_key_set and secret_key_set):
            raise ValueError("ORDER_SUBMISSION_ENABLED requires complete Alpaca paper credentials")
        data_url = self.alpaca_data_base_url.rstrip("/").lower()
        if data_url != "https://data.alpaca.markets":
            raise ValueError("ALPACA_DATA_BASE_URL must be the exact Alpaca data endpoint")
        if self.alpaca_request_timeout_seconds <= 0:
            raise ValueError("ALPACA_REQUEST_TIMEOUT_SECONDS must be positive")
        if not 0 <= self.alpaca_max_safe_retries <= 5:
            raise ValueError("ALPACA_MAX_SAFE_RETRIES must be between 0 and 5")
        if self.alpaca_stock_feed not in {"iex", "delayed_sip", "sip"}:
            raise ValueError("ALPACA_STOCK_FEED is unsupported")
        if self.alpaca_option_feed not in {"indicative", "opra"}:
            raise ValueError("ALPACA_OPTION_FEED is unsupported")
        if not self.openai_model.strip():
            raise ValueError("OPENAI_MODEL cannot be blank")
        azure_endpoint_set = bool(
            self.azure_openai_endpoint and self.azure_openai_endpoint.strip()
        )
        azure_deployment_set = bool(
            self.azure_openai_deployment and self.azure_openai_deployment.strip()
        )
        if azure_endpoint_set != azure_deployment_set:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT must be configured together"
            )
        if azure_endpoint_set:
            endpoint = urlparse(self.azure_openai_endpoint or "")
            allowed_hosts = (".openai.azure.com", ".cognitiveservices.azure.com")
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or not endpoint.hostname.endswith(allowed_hosts)
            ):
                raise ValueError(
                    "AZURE_OPENAI_ENDPOINT must be an HTTPS Azure OpenAI resource endpoint"
                )
        if self.openai_request_timeout_seconds <= 0:
            raise ValueError("OPENAI_REQUEST_TIMEOUT_SECONDS must be positive")
        if not 0 <= self.openai_max_retries <= 3:
            raise ValueError("OPENAI_MAX_RETRIES must be between 0 and 3")
        if not 1_000 <= self.openai_max_input_chars <= 50_000:
            raise ValueError("OPENAI_MAX_INPUT_CHARS must be between 1000 and 50000")
        if not 60 <= self.market_scan_lookback_days <= 730:
            raise ValueError("MARKET_SCAN_LOOKBACK_DAYS must be between 60 and 730")
        if self.market_max_data_age_seconds <= 0:
            raise ValueError("MARKET_MAX_DATA_AGE_SECONDS must be positive")
        if not Decimal("0.10") <= self.opportunity_signal_threshold <= Decimal("1"):
            raise ValueError("OPPORTUNITY_SIGNAL_THRESHOLD must be between 0.10 and 1")
        if self.opportunity_min_volume_ratio < 0:
            raise ValueError("OPPORTUNITY_MIN_VOLUME_RATIO cannot be negative")
        percentage_values = (
            self.risk_max_risk_per_trade_pct,
            self.risk_max_portfolio_exposure_pct,
            self.risk_max_underlying_exposure_pct,
            self.risk_max_daily_loss_pct,
            self.risk_max_bid_ask_spread_pct,
            self.option_max_strike_distance_pct,
            self.exit_stop_loss_pct,
            self.exit_take_profit_pct,
        )
        if any(value <= 0 or value > 1 for value in percentage_values):
            raise ValueError("Risk, option, and exit percentages must be in the interval (0, 1]")
        if self.risk_max_premium_per_trade <= 0:
            raise ValueError("RISK_MAX_PREMIUM_PER_TRADE must be positive")
        if not 0 <= self.risk_min_ai_confidence <= 1:
            raise ValueError("RISK_MIN_AI_CONFIDENCE must be between 0 and 1")
        if self.risk_max_open_positions <= 0 or self.risk_max_consecutive_losses <= 0:
            raise ValueError("Risk count limits must be positive")
        timing_values = (
            self.risk_cooldown_minutes,
            self.risk_max_quote_age_seconds,
            self.risk_min_dte,
            self.option_target_dte,
            self.exit_max_holding_days,
            self.exit_dte,
            self.agent_scan_interval_seconds,
        )
        if min(timing_values) <= 0:
            raise ValueError("Trading timing values must be positive")
        if self.risk_min_dte > self.risk_max_dte:
            raise ValueError("RISK_MIN_DTE cannot exceed RISK_MAX_DTE")
        if not self.risk_min_dte <= self.option_target_dte <= self.risk_max_dte:
            raise ValueError("OPTION_TARGET_DTE must be inside the risk DTE window")
        if self.risk_kill_switch and self.order_submission_enabled:
            raise ValueError(
                "ORDER_SUBMISSION_ENABLED cannot be true while the kill switch is active"
            )
        control_token = self.control_api_token_value
        if control_token and len(control_token) < 32:
            raise ValueError("CONTROL_API_TOKEN must contain at least 32 characters")
        if (
            self.order_submission_enabled or self.agent_autonomy_enabled or self.demo_mode
        ) and not control_token:
            raise ValueError(
                "CONTROL_API_TOKEN is required when execution, autonomy, or demo mode is enabled"
            )
        if not self.alpaca_cli_executable.strip() or self.alpaca_cli_timeout_seconds <= 0:
            raise ValueError("Alpaca CLI executable and timeout must be valid")
        if not self.watchlist_symbols:
            raise ValueError("MARKET_WATCHLIST must contain at least one valid symbol")
        if not self.api_v1_prefix.startswith("/"):
            raise ValueError("API_V1_PREFIX must begin with '/'")
        if not self.cors_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one exact origin")
        if self.app_environment is not Environment.TEST and not self.database_url.startswith(
            "postgresql+asyncpg://"
        ):
            raise ValueError("PostgreSQL with the asyncpg driver is required outside tests")
        if self.database_pool_size <= 0 or self.database_max_overflow < 0:
            raise ValueError("Database pool size must be positive and overflow cannot be negative")
        if self.database_pool_timeout_seconds <= 0:
            raise ValueError("DATABASE_POOL_TIMEOUT_SECONDS must be positive")
        if self.database_transaction_pooler and (
            self.order_submission_enabled or self.agent_autonomy_enabled
        ):
            raise ValueError(
                "Trading requires a direct or session-mode database connection for advisory locks"
            )
        return self

    @property
    def alpaca_credentials_configured(self) -> bool:
        return self._secret_is_set(self.alpaca_api_key) and self._secret_is_set(
            self.alpaca_secret_key
        )

    @property
    def watchlist_symbols(self) -> tuple[str, ...]:
        symbols = tuple(
            dict.fromkeys(symbol.strip().upper() for symbol in self.market_watchlist.split(","))
        )
        if any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) for symbol in symbols):
            return ()
        return symbols

    @property
    def cors_origins(self) -> tuple[str, ...]:
        origins = tuple(
            dict.fromkeys(
                origin.strip().rstrip("/")
                for origin in self.cors_allowed_origins.split(",")
            )
        )
        for origin in origins:
            parsed = urlparse(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                return ()
        return origins

    @property
    def openai_configured(self) -> bool:
        return self._secret_is_set(self.openai_api_key)

    @property
    def azure_openai_configured(self) -> bool:
        return bool(
            self.azure_openai_endpoint
            and self.azure_openai_endpoint.strip()
            and self.azure_openai_deployment
            and self.azure_openai_deployment.strip()
        )

    @property
    def llm_model(self) -> str:
        if self.azure_openai_configured:
            assert self.azure_openai_deployment is not None
            return self.azure_openai_deployment.strip()
        return self.openai_model.strip()

    @property
    def llm_base_url(self) -> str | None:
        if not self.azure_openai_configured:
            return None
        assert self.azure_openai_endpoint is not None
        endpoint = self.azure_openai_endpoint.rstrip("/")
        if endpoint.endswith("/openai/v1"):
            return f"{endpoint}/"
        return f"{endpoint}/openai/v1/"

    @property
    def control_api_token_value(self) -> str | None:
        if not self._secret_is_set(self.control_api_token):
            return None
        assert self.control_api_token is not None
        return self.control_api_token.get_secret_value().strip()

    @staticmethod
    def _secret_is_set(value: SecretStr | None) -> bool:
        return value is not None and bool(value.get_secret_value().strip())

    def public_summary(self) -> dict[str, str | bool]:
        """Return only values safe to expose through diagnostics."""
        return {
            "environment": self.app_environment.value,
            "paper_trading": True,
            "trading_host": "paper-api.alpaca.markets",
            "credentials_configured": self.alpaca_credentials_configured,
            "order_submission_enabled": self.order_submission_enabled,
            "llm_configured": self.openai_configured,
            "llm_provider": "azure_openai" if self.azure_openai_configured else "openai",
            "agent_autonomy_enabled": self.agent_autonomy_enabled,
            "demo_mode": self.demo_mode,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
