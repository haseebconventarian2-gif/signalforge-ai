from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.broker import Bar, HistoricalBarsQuery, Page, StockSnapshot, Trade
from app.services.market_data import MarketDataService


class FakeMarketDataProvider:
    def __init__(self) -> None:
        self.queries: list[HistoricalBarsQuery] = []

    async def get_historical_bars(self, query: HistoricalBarsQuery) -> Page[Bar]:
        self.queries.append(query)
        timestamp = datetime(2026, 9, 2, tzinfo=UTC)
        bar = Bar(
            symbol="SPY",
            timestamp=timestamp,
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=Decimal("1000"),
        )
        return Page(items=(bar,), next_page_token="next" if not query.page_token else None)

    async def get_stock_snapshots(self, symbols: tuple[str, ...]) -> tuple[StockSnapshot, ...]:
        return (
            StockSnapshot(
                symbol="SPY",
                latest_trade=Trade(
                    timestamp=datetime(2026, 9, 3, tzinfo=UTC),
                    price=Decimal("103"),
                    size=Decimal("10"),
                ),
            ),
        )

    async def get_option_snapshots(self, symbols: tuple[str, ...]) -> tuple:  # pragma: no cover
        return ()

    async def close(self) -> None:  # pragma: no cover
        return None


async def test_service_follows_pagination_and_prefers_latest_trade() -> None:
    provider = FakeMarketDataProvider()
    service = MarketDataService(provider, lookback_days=180)
    as_of = datetime(2026, 9, 3, 12, tzinfo=UTC)

    result = await service.load_watchlist(("SPY",), as_of=as_of)

    assert len(provider.queries) == 2
    assert provider.queries[0].start == as_of - timedelta(days=180)
    assert provider.queries[1].page_token == "next"
    assert result[0].underlying_price == 103
    assert result[0].data_timestamp == datetime(2026, 9, 3, tzinfo=UTC)
