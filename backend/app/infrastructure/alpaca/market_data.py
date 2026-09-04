from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import BrokerValidationError
from app.domain.broker import (
    Bar,
    HistoricalBarsQuery,
    OptionSnapshot,
    Page,
    StockSnapshot,
)
from app.infrastructure.alpaca.parsing import (
    parse_bar,
    parse_option_snapshot,
    parse_stock_snapshot,
)
from app.infrastructure.alpaca.transport import AlpacaHttpTransport, AlpacaResponse


class AlpacaMarketDataClient:
    """Normalized stock and option data adapter using subscription-safe defaults."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._http = AlpacaHttpTransport(
            settings,
            base_url="https://data.alpaca.markets",
            transport=transport,
        )

    async def get_historical_bars(self, query: HistoricalBarsQuery) -> Page[Bar]:
        params: dict[str, str | int | bool] = {
            "symbols": ",".join(query.symbols),
            "timeframe": query.timeframe,
            "start": query.start.isoformat(),
            "limit": query.limit,
            "feed": self._settings.alpaca_stock_feed,
            "adjustment": "all",
            "sort": "asc",
        }
        if query.end:
            params["end"] = query.end.isoformat()
        if query.page_token:
            params["page_token"] = query.page_token
        response = await self._http.request(
            "GET", "/v2/stocks/bars", params=params, safe_to_retry=True
        )
        payload = self._mapping(response)
        bars_payload = payload.get("bars", {})
        if not isinstance(bars_payload, dict):
            raise BrokerValidationError("Alpaca bars response has an invalid shape")
        bars = tuple(
            parse_bar(symbol, bar)
            for symbol, symbol_bars in bars_payload.items()
            for bar in symbol_bars
        )
        return Page[Bar](
            items=bars,
            next_page_token=payload.get("next_page_token"),
            provider_request_id=response.request_id,
        )

    async def get_stock_snapshots(self, symbols: tuple[str, ...]) -> tuple[StockSnapshot, ...]:
        self._validate_symbol_count(symbols)
        response = await self._http.request(
            "GET",
            "/v2/stocks/snapshots",
            params={"symbols": ",".join(symbols), "feed": self._settings.alpaca_stock_feed},
            safe_to_retry=True,
        )
        payload = self._mapping(response)
        return tuple(
            parse_stock_snapshot(symbol, snapshot, response.request_id)
            for symbol, snapshot in payload.items()
        )

    async def get_option_snapshots(self, symbols: tuple[str, ...]) -> tuple[OptionSnapshot, ...]:
        self._validate_symbol_count(symbols, maximum=100)
        response = await self._http.request(
            "GET",
            "/v1beta1/options/snapshots",
            params={
                "symbols": ",".join(symbols),
                "feed": self._settings.alpaca_option_feed,
                "limit": 100,
            },
            safe_to_retry=True,
        )
        payload = self._mapping(response)
        snapshots_payload = payload.get("snapshots", payload)
        if not isinstance(snapshots_payload, dict):
            raise BrokerValidationError("Alpaca option snapshots response has an invalid shape")
        return tuple(
            parse_option_snapshot(symbol, snapshot, response.request_id)
            for symbol, snapshot in snapshots_payload.items()
        )

    @staticmethod
    def _validate_symbol_count(symbols: tuple[str, ...], maximum: int = 200) -> None:
        if not symbols:
            raise BrokerValidationError("At least one symbol is required")
        if len(symbols) > maximum:
            raise BrokerValidationError(f"No more than {maximum} symbols are allowed")

    @staticmethod
    def _mapping(response: AlpacaResponse) -> dict[str, Any]:
        if not isinstance(response.payload, dict):
            raise BrokerValidationError(
                "Alpaca returned an unexpected market-data response",
                context={"provider_request_id": response.request_id},
            )
        return response.payload

    async def close(self) -> None:
        await self._http.close()
