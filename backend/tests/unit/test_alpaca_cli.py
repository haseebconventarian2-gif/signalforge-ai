from __future__ import annotations

import shutil

import pytest

from app.core.config import Environment, Settings
from app.infrastructure.alpaca.cli import AlpacaCliVerifier


def settings() -> Settings:
    return Settings(
        app_environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        alpaca_api_key="paper-key",
        alpaca_secret_key="paper-secret",
        alpaca_cli_executable="definitely-not-installed-signalforge-cli",
    )


@pytest.mark.asyncio
async def test_missing_cli_is_reported_without_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)

    result = await AlpacaCliVerifier(settings()).verify()

    assert result.installed is False
    assert result.configured is True
    assert result.connected is False
    assert result.paper_verified is False
    assert "paper-key" not in result.model_dump_json()
    assert "paper-secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b'{"status":"ACTIVE","cash":"100000"}', "ACTIVE"),
        (b'{"cash":"100000"}', None),
        (b"not-json", None),
    ],
)
def test_cli_output_is_reduced_to_account_status(payload: bytes, expected: str | None) -> None:
    assert AlpacaCliVerifier._account_status(payload) == expected
