from __future__ import annotations

from typing import Any

from app.domain.broker import Bar, OptionSnapshot, Quote, StockSnapshot, Trade


def parse_bar(symbol: str, payload: dict[str, Any]) -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=payload["t"],
        open=payload["o"],
        high=payload["h"],
        low=payload["l"],
        close=payload["c"],
        volume=payload["v"],
        trade_count=payload.get("n"),
        volume_weighted_price=payload.get("vw"),
    )


def parse_quote(payload: dict[str, Any] | None) -> Quote | None:
    if not payload:
        return None
    return Quote(
        timestamp=payload["t"],
        bid_price=payload["bp"],
        bid_size=payload["bs"],
        ask_price=payload["ap"],
        ask_size=payload["as"],
    )


def parse_trade(payload: dict[str, Any] | None) -> Trade | None:
    if not payload:
        return None
    return Trade(timestamp=payload["t"], price=payload["p"], size=payload["s"])


def parse_stock_snapshot(
    symbol: str, payload: dict[str, Any], request_id: str | None
) -> StockSnapshot:
    return StockSnapshot(
        symbol=symbol,
        latest_trade=parse_trade(payload.get("latestTrade")),
        latest_quote=parse_quote(payload.get("latestQuote")),
        minute_bar=parse_bar(symbol, payload["minuteBar"]) if payload.get("minuteBar") else None,
        daily_bar=parse_bar(symbol, payload["dailyBar"]) if payload.get("dailyBar") else None,
        previous_daily_bar=(
            parse_bar(symbol, payload["prevDailyBar"]) if payload.get("prevDailyBar") else None
        ),
        provider_request_id=request_id,
    )


def parse_option_snapshot(
    symbol: str, payload: dict[str, Any], request_id: str | None
) -> OptionSnapshot:
    return OptionSnapshot(
        symbol=symbol,
        latest_trade=parse_trade(payload.get("latestTrade")),
        latest_quote=parse_quote(payload.get("latestQuote")),
        implied_volatility=payload.get("impliedVolatility"),
        greeks=payload.get("greeks"),
        provider_request_id=request_id,
    )
