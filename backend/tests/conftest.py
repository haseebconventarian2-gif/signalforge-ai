from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

# Tests must not inherit execution controls from a developer's real .env file.
os.environ.update(
    {
        "ORDER_SUBMISSION_ENABLED": "false",
        "AGENT_AUTONOMY_ENABLED": "false",
        "DEMO_MODE": "false",
        "RISK_KILL_SWITCH": "false",
        "DATABASE_TRANSACTION_POOLER": "false",
        "MARKET_WATCHLIST": (
            "SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMD,TSLA,META,AMZN,GOOGL,"
            "NFLX,AVGO,JPM,BAC,XOM,COIN,PLTR,INTC,TLT"
        ),
    }
)

from app.core.config import Environment, Settings
from app.factory import create_app
from app.infrastructure.database import models  # noqa: F401
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import Database


def test_settings(database_url: str = "sqlite+aiosqlite:///:memory:") -> Settings:
    return Settings(
        app_environment=Environment.TEST,
        database_url=database_url,
        alpaca_api_key=None,
        alpaca_secret_key=None,
        openai_api_key=None,
        azure_openai_endpoint=None,
        azure_openai_deployment=None,
        control_api_token=None,
        order_submission_enabled=False,
    )


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(test_settings())) as test_client:
        yield test_client
