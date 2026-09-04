from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.market_intelligence import (
    DirectionalBias,
    IndicatorSnapshot,
    MarketSeries,
)
from app.services.opportunity import OpportunityDetector

NOW = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)


def indicators(*, bullish: bool = True, volume_ratio: str = "1.5") -> IndicatorSnapshot:
    direction = Decimal("1") if bullish else Decimal("-1")
    return IndicatorSnapshot(
        period_return=direction * Decimal("0.01"),
        sma_20=Decimal("100"),
        ema_20=Decimal("102") if bullish else Decimal("98"),
        ema_50=Decimal("100"),
        rsi_14=Decimal("65") if bullish else Decimal("35"),
        macd=direction,
        macd_signal=direction * Decimal("0.4"),
        macd_histogram=direction * Decimal("0.6"),
        atr_14=Decimal("2"),
        volume_ratio_20=Decimal(volume_ratio),
        annualized_volatility_20=Decimal("0.2"),
        recent_high_20=Decimal("110"),
        recent_low_20=Decimal("90"),
        momentum_10=direction * Decimal("0.05"),
        trend_strength=Decimal("1"),
    )


def series(*, bullish: bool = True, age_seconds: int = 10) -> MarketSeries:
    return MarketSeries(
        symbol="SPY",
        bars=(),
        underlying_price=Decimal("103") if bullish else Decimal("97"),
        data_timestamp=NOW - timedelta(seconds=age_seconds),
    )


def detector(*, threshold: str = "0.35") -> OpportunityDetector:
    return OpportunityDetector(
        signal_threshold=Decimal(threshold),
        minimum_volume_ratio=Decimal("0.75"),
        maximum_data_age_seconds=300,
    )


def test_bullish_candidate_has_transparent_weighted_score() -> None:
    candidate = detector().detect(series(), indicators(), observed_at=NOW)

    assert candidate is not None
    assert candidate.directional_bias is DirectionalBias.BULLISH
    assert candidate.signal_score == Decimal("0.7875")
    assert candidate.data_freshness_seconds == 10
    assert candidate.reasons == (
        "EMA 20 is above EMA 50",
        "MACD histogram is positive",
        "10-period momentum is positive",
        "RSI is above its neutral level",
        "Price is above SMA 20",
    )


def test_bearish_candidate_uses_same_symmetric_rules() -> None:
    candidate = detector().detect(series(bullish=False), indicators(bullish=False), observed_at=NOW)

    assert candidate is not None
    assert candidate.directional_bias is DirectionalBias.BEARISH
    assert candidate.signal_score == Decimal("0.7875")
    assert all("below" in reason or "negative" in reason for reason in candidate.reasons)


def test_detector_rejects_weak_stale_and_low_volume_inputs() -> None:
    assert detector(threshold="0.90").detect(series(), indicators(), observed_at=NOW) is None
    assert detector().detect(series(age_seconds=301), indicators(), observed_at=NOW) is None
    assert detector().detect(series(), indicators(volume_ratio="0.74"), observed_at=NOW) is None
