from __future__ import annotations

from datetime import datetime, timedelta

from app.core.exceptions import BrokerValidationError
from app.domain.broker import Bar, HistoricalBarsQuery, MarketDataProvider, StockSnapshot
from app.domain.market_intelligence import MarketSeries


class MarketDataService:
    """Load and align normalized daily bars and current underlying prices."""

    def __init__(self, provider: MarketDataProvider, *, lookback_days: int) -> None:
        self._provider = provider
        self._lookback_days = lookback_days

    async def load_watchlist(
        self, symbols: tuple[str, ...], *, as_of: datetime
    ) -> tuple[MarketSeries, ...]:
        if not symbols:
            return ()
        query = HistoricalBarsQuery(
            symbols=symbols,
            timeframe="1Day",
            start=as_of - timedelta(days=self._lookback_days),
            end=as_of,
            limit=10_000,
        )
        bars: list[Bar] = []
        seen_tokens: set[str] = set()
        for _ in range(20):
            page = await self._provider.get_historical_bars(query)
            bars.extend(page.items)
            token = page.next_page_token
            if not token:
                break
            if token in seen_tokens:
                raise BrokerValidationError("Market-data pagination returned a repeated token")
            seen_tokens.add(token)
            query = query.model_copy(update={"page_token": token})
        else:
            raise BrokerValidationError("Market-data pagination exceeded the safety limit")

        snapshots = {
            snapshot.symbol.upper(): snapshot
            for snapshot in await self._provider.get_stock_snapshots(symbols)
        }
        return tuple(
            series
            for symbol in symbols
            if (series := self._build_series(symbol, bars, snapshots.get(symbol))) is not None
        )

    @staticmethod
    def _build_series(
        symbol: str, bars: list[Bar], snapshot: StockSnapshot | None
    ) -> MarketSeries | None:
        symbol_bars = tuple(
            sorted(
                (bar for bar in bars if bar.symbol.upper() == symbol),
                key=lambda bar: bar.timestamp,
            )
        )
        if not symbol_bars:
            return None
        if snapshot and snapshot.latest_trade:
            price = snapshot.latest_trade.price
            data_timestamp = snapshot.latest_trade.timestamp
        elif snapshot and snapshot.minute_bar:
            price = snapshot.minute_bar.close
            data_timestamp = snapshot.minute_bar.timestamp
        elif snapshot and snapshot.daily_bar:
            price = snapshot.daily_bar.close
            data_timestamp = snapshot.daily_bar.timestamp
        else:
            price = symbol_bars[-1].close
            data_timestamp = symbol_bars[-1].timestamp
        return MarketSeries(
            symbol=symbol,
            bars=symbol_bars,
            underlying_price=price,
            data_timestamp=data_timestamp,
        )
