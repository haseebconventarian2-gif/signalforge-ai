import pytest
from pydantic import ValidationError

from app.api.dependencies import require_control_authorization
from app.core.config import PAPER_TRADING_ORIGIN, Environment, Settings
from app.core.exceptions import ControlAuthenticationError, ControlUnavailableError


def make_settings(**overrides) -> Settings:
    values = {
        "app_environment": Environment.TEST,
        "database_url": "sqlite+aiosqlite:///:memory:",
        "alpaca_api_key": None,
        "alpaca_secret_key": None,
        "azure_openai_endpoint": None,
        "azure_openai_deployment": None,
        "control_api_token": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_default_trading_endpoint_is_exact_paper_origin() -> None:
    settings = make_settings()
    assert settings.alpaca_trading_base_url == PAPER_TRADING_ORIGIN
    assert settings.public_summary()["paper_trading"] is True


@pytest.mark.parametrize(
    "url",
    [
        "https://api." + "alpaca.markets",
        "http://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets.evil.example",
        "https://example.com",
    ],
)
def test_non_paper_trading_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match="exact Alpaca paper endpoint"):
        make_settings(alpaca_trading_base_url=url)


def test_live_trade_flag_is_rejected() -> None:
    with pytest.raises(ValidationError, match="paper-only"):
        make_settings(alpaca_live_trade=True)


def test_partial_alpaca_credentials_are_rejected() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        make_settings(alpaca_api_key="paper-key")


def test_blank_credentials_are_unconfigured() -> None:
    settings = make_settings(alpaca_api_key="", alpaca_secret_key="")
    assert settings.alpaca_credentials_configured is False


def test_submission_switch_requires_credentials() -> None:
    with pytest.raises(ValidationError, match="requires complete"):
        make_settings(order_submission_enabled=True)


def test_execution_requires_a_strong_control_token() -> None:
    with pytest.raises(ValidationError, match="CONTROL_API_TOKEN is required"):
        make_settings(
            alpaca_api_key="paper-key",
            alpaca_secret_key="paper-secret",
            order_submission_enabled=True,
        )
    with pytest.raises(ValidationError, match="at least 32"):
        make_settings(control_api_token="too-short")


def test_control_authorization_fails_closed_and_accepts_exact_token() -> None:
    disabled = make_settings()
    with pytest.raises(ControlUnavailableError):
        require_control_authorization(disabled, None)

    enabled = make_settings(control_api_token="a" * 32)
    with pytest.raises(ControlAuthenticationError):
        require_control_authorization(enabled, "wrong-token")
    assert require_control_authorization(enabled, "a" * 32) is None


def test_transaction_pooler_cannot_enable_distributed_trading() -> None:
    with pytest.raises(ValidationError, match="direct or session-mode"):
        make_settings(
            alpaca_api_key="paper-key",
            alpaca_secret_key="paper-secret",
            control_api_token="a" * 32,
            database_transaction_pooler=True,
            order_submission_enabled=True,
        )


def test_secrets_are_not_in_repr_or_public_summary() -> None:
    settings = make_settings(
        alpaca_api_key="paper-key",
        alpaca_secret_key="paper-secret",
        openai_api_key="openai-secret",
    )
    rendered = repr(settings)
    summary = settings.public_summary()
    assert "paper-key" not in rendered
    assert "paper-secret" not in rendered
    assert "openai-secret" not in rendered
    assert "paper-key" not in str(summary)
    assert "paper-secret" not in str(summary)
    assert "openai-secret" not in str(summary)
    assert summary["credentials_configured"] is True
    assert summary["llm_configured"] is True


def test_non_postgres_database_rejected_outside_tests() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL with the asyncpg driver"):
        Settings(
            app_environment=Environment.DEVELOPMENT,
            database_url="sqlite:///local.db",
            azure_openai_endpoint=None,
            azure_openai_deployment=None,
        )


def test_market_watchlist_is_normalized_and_deduplicated() -> None:
    settings = make_settings(market_watchlist=" spy,QQQ,SPY ")

    assert settings.watchlist_symbols == ("SPY", "QQQ")


def test_cors_origins_are_exact_normalized_origins() -> None:
    settings = make_settings(
        cors_allowed_origins="https://signalforge.vercel.app/,http://localhost:5173"
    )

    assert settings.cors_origins == (
        "https://signalforge.vercel.app",
        "http://localhost:5173",
    )


@pytest.mark.parametrize(
    "origins",
    ["*", "signalforge.vercel.app", "https://signalforge.vercel.app/path"],
)
def test_cors_rejects_wildcards_and_non_origins(origins: str) -> None:
    with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS"):
        make_settings(cors_allowed_origins=origins)


@pytest.mark.parametrize("watchlist", ["", "SPY,$BAD", "TOO-LONG-SYMBOL-NAME"])
def test_invalid_market_watchlist_is_rejected(watchlist: str) -> None:
    with pytest.raises(ValidationError, match="MARKET_WATCHLIST"):
        make_settings(market_watchlist=watchlist)


def test_openai_retry_and_input_limits_are_bounded() -> None:
    with pytest.raises(ValidationError, match="OPENAI_MAX_RETRIES"):
        make_settings(openai_max_retries=4)
    with pytest.raises(ValidationError, match="OPENAI_MAX_INPUT_CHARS"):
        make_settings(openai_max_input_chars=999)


def test_azure_openai_requires_endpoint_and_deployment_together() -> None:
    with pytest.raises(ValidationError, match="must be configured together"):
        make_settings(azure_openai_endpoint="https://signalforge.openai.azure.com")


def test_azure_openai_configuration_builds_v1_url_and_uses_deployment() -> None:
    settings = make_settings(
        openai_api_key="azure-resource-key",
        azure_openai_endpoint="https://signalforge.openai.azure.com/",
        azure_openai_deployment="trading-gpt-4-1",
    )

    assert settings.openai_configured is True
    assert settings.azure_openai_configured is True
    assert settings.llm_base_url == "https://signalforge.openai.azure.com/openai/v1/"
    assert settings.llm_model == "trading-gpt-4-1"
    assert settings.public_summary()["llm_provider"] == "azure_openai"


def test_azure_ai_services_endpoint_is_supported() -> None:
    settings = make_settings(
        openai_api_key="azure-resource-key",
        azure_openai_endpoint="https://signalforge.cognitiveservices.azure.com/",
        azure_openai_deployment="trading-gpt-4-1",
    )

    assert settings.llm_base_url == (
        "https://signalforge.cognitiveservices.azure.com/openai/v1/"
    )


def test_azure_openai_rejects_untrusted_endpoint() -> None:
    with pytest.raises(ValidationError, match="Azure OpenAI resource endpoint"):
        make_settings(
            azure_openai_endpoint="https://example.com",
            azure_openai_deployment="trading-model",
        )
