from __future__ import annotations

from datetime import UTC, datetime

from app.core.exceptions import IndicatorCalculationError
from app.domain.market_intelligence import MarketScanResult
from app.services.indicators import IndicatorEngine
from app.services.market_data import MarketDataService
from app.services.opportunity import OpportunityDetector


class MarketScanner:
    """Orchestrate one bounded, read-only scan across the configured watchlist."""

    def __init__(
        self,
        market_data: MarketDataService,
        indicators: IndicatorEngine,
        detector: OpportunityDetector,
        *,
        watchlist: tuple[str, ...],
    ) -> None:
        self._market_data = market_data
        self._indicators = indicators
        self._detector = detector
        self._watchlist = watchlist

    async def scan(self, *, observed_at: datetime | None = None) -> MarketScanResult:
        timestamp = observed_at or datetime.now(UTC)
        series_set = await self._market_data.load_watchlist(self._watchlist, as_of=timestamp)
        opportunities = []
        for series in series_set:
            try:
                snapshot = self._indicators.calculate(series.bars)
            except IndicatorCalculationError:
                continue
            candidate = self._detector.detect(series, snapshot, observed_at=timestamp)
            if candidate:
                opportunities.append(candidate)
        opportunities.sort(key=lambda item: (-item.signal_score, item.symbol))
        return MarketScanResult(
            timestamp=timestamp,
            watchlist=self._watchlist,
            opportunities=tuple(opportunities),
        )
