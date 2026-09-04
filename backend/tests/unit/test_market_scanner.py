from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.broker import Bar
from app.domain.market_intelligence import DirectionalBias, MarketSeries
from app.services.indicators import IndicatorEngine
from app.services.opportunity import OpportunityDetector
from app.services.scanner import MarketScanner

NOW = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)


class FakeMarketDataService:
    async def load_watchlist(
        self, symbols: tuple[str, ...], *, as_of: datetime
    ) -> tuple[MarketSeries, ...]:
        return (
            MarketSeries(
                symbol="SPY",
                bars=make_bars("SPY", 60),
                underlying_price=Decimal("160"),
                data_timestamp=as_of,
            ),
            MarketSeries(
                symbol="QQQ",
                bars=make_bars("QQQ", 20),
                underlying_price=Decimal("120"),
                data_timestamp=as_of,
            ),
        )


def make_bars(symbol: str, count: int) -> tuple[Bar, ...]:
    start = NOW - timedelta(days=count)
    return tuple(
        Bar(
            symbol=symbol,
            timestamp=start + timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(102 + index),
            low=Decimal(99 + index),
            close=Decimal(101 + index),
            volume=Decimal("1000"),
        )
        for index in range(count)
    )


async def test_scanner_isolates_insufficient_history_and_returns_candidates() -> None:
    scanner = MarketScanner(
        FakeMarketDataService(),  # type: ignore[arg-type]
        IndicatorEngine(),
        OpportunityDetector(
            signal_threshold=Decimal("0.30"),
            minimum_volume_ratio=Decimal("0.75"),
            maximum_data_age_seconds=300,
        ),
        watchlist=("SPY", "QQQ"),
    )

    result = await scanner.scan(observed_at=NOW)

    assert result.watchlist == ("SPY", "QQQ")
    assert len(result.opportunities) == 1
    assert result.opportunities[0].symbol == "SPY"
    assert result.opportunities[0].directional_bias is DirectionalBias.BULLISH
