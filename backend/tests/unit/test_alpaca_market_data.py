from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.core.exceptions import BrokerValidationError
from app.domain.broker import HistoricalBarsQuery
from app.infrastructure.alpaca.market_data import AlpacaMarketDataClient
from tests.unit.test_alpaca_broker import OPTION_SYMBOL, response, settings

NOW = "2026-09-03T15:00:00Z"


async def test_historical_bars_are_normalized_and_paginated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["feed"] == "iex"
        return response(
            request,
            200,
            {
                "bars": {
                    "AAPL": [
                        {
                            "t": NOW,
                            "o": 200,
                            "h": 205,
                            "l": 198,
                            "c": 203,
                            "v": 10000,
                            "n": 500,
                            "vw": 202,
                        }
                    ]
                },
                "next_page_token": "page-2",
            },
        )

    client = AlpacaMarketDataClient(settings(), transport=httpx.MockTransport(handler))
    page = await client.get_historical_bars(
        HistoricalBarsQuery(
            symbols=("AAPL",),
            timeframe="1Day",
            start=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    await client.close()

    assert page.items[0].close == 203
    assert page.items[0].symbol == "AAPL"
    assert page.next_page_token == "page-2"


async def test_stock_and_option_snapshots_are_normalized() -> None:
    quote = {"t": NOW, "bp": 2.4, "bs": 10, "ap": 2.5, "as": 8}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/stocks/snapshots":
            return response(
                request,
                200,
                {"AAPL": {"latestQuote": {**quote, "bp": 202, "ap": 202.1}}},
            )
        return response(
            request,
            200,
            {
                "snapshots": {
                    OPTION_SYMBOL: {
                        "latestQuote": quote,
                        "impliedVolatility": 0.31,
                        "greeks": {"delta": 0.51, "gamma": 0.04, "theta": -0.08},
                    }
                }
            },
        )

    client = AlpacaMarketDataClient(settings(), transport=httpx.MockTransport(handler))
    stocks = await client.get_stock_snapshots(("AAPL",))
    options = await client.get_option_snapshots((OPTION_SYMBOL,))
    await client.close()

    assert stocks[0].latest_quote is not None
    assert stocks[0].latest_quote.ask_price == Decimal("202.1")
    assert options[0].latest_quote is not None
    assert options[0].greeks is not None
    assert options[0].greeks.delta == Decimal("0.51")


async def test_option_snapshot_request_enforces_provider_limit() -> None:
    client = AlpacaMarketDataClient(settings(), transport=httpx.MockTransport(lambda _: None))
    with pytest.raises(BrokerValidationError, match="100"):
        await client.get_option_snapshots(tuple(f"OPT{i}" for i in range(101)))
    await client.close()
