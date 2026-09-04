from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.domain.market_intelligence import (
    CandidateOpportunity,
    DirectionalBias,
    IndicatorSnapshot,
    MarketSeries,
)


class OpportunityDetector:
    """Convert independent indicator evidence into deterministic candidates."""

    def __init__(
        self,
        *,
        signal_threshold: Decimal,
        minimum_volume_ratio: Decimal,
        maximum_data_age_seconds: int,
    ) -> None:
        self._signal_threshold = signal_threshold
        self._minimum_volume_ratio = minimum_volume_ratio
        self._maximum_data_age_seconds = maximum_data_age_seconds

    def detect(
        self,
        series: MarketSeries,
        indicators: IndicatorSnapshot,
        *,
        observed_at: datetime,
    ) -> CandidateOpportunity | None:
        freshness = max(0, int((observed_at - series.data_timestamp).total_seconds()))
        if freshness > self._maximum_data_age_seconds:
            return None
        if indicators.volume_ratio_20 < self._minimum_volume_ratio:
            return None

        atr = indicators.atr_14
        trend = self._clamp((indicators.ema_20 - indicators.ema_50) / atr) if atr else Decimal("0")
        macd = self._clamp(indicators.macd_histogram / atr) if atr else Decimal("0")
        momentum = self._clamp(indicators.momentum_10 / Decimal("0.05"))
        rsi = self._clamp((indicators.rsi_14 - Decimal("50")) / Decimal("20"))
        price = (
            self._clamp((series.underlying_price - indicators.sma_20) / atr)
            if atr
            else Decimal("0")
        )
        signed_score = (
            Decimal("0.30") * trend
            + Decimal("0.25") * macd
            + Decimal("0.20") * momentum
            + Decimal("0.15") * rsi
            + Decimal("0.10") * price
        )
        score = abs(signed_score)
        if score < self._signal_threshold:
            return None

        bias = DirectionalBias.BULLISH if signed_score > 0 else DirectionalBias.BEARISH
        return CandidateOpportunity(
            symbol=series.symbol,
            timestamp=observed_at,
            data_timestamp=series.data_timestamp,
            underlying_price=series.underlying_price,
            directional_bias=bias,
            signal_score=score.quantize(Decimal("0.0001")),
            indicator_snapshot=indicators,
            reasons=self._reasons(indicators, series.underlying_price, bias),
            data_freshness_seconds=freshness,
        )

    @staticmethod
    def _clamp(value: Decimal) -> Decimal:
        return max(Decimal("-1"), min(Decimal("1"), value))

    @staticmethod
    def _reasons(
        indicators: IndicatorSnapshot,
        price: Decimal,
        bias: DirectionalBias,
    ) -> tuple[str, ...]:
        if bias is DirectionalBias.BULLISH:
            evidence = (
                (indicators.ema_20 > indicators.ema_50, "EMA 20 is above EMA 50"),
                (indicators.macd_histogram > 0, "MACD histogram is positive"),
                (indicators.momentum_10 > 0, "10-period momentum is positive"),
                (indicators.rsi_14 > 50, "RSI is above its neutral level"),
                (price > indicators.sma_20, "Price is above SMA 20"),
            )
        else:
            evidence = (
                (indicators.ema_20 < indicators.ema_50, "EMA 20 is below EMA 50"),
                (indicators.macd_histogram < 0, "MACD histogram is negative"),
                (indicators.momentum_10 < 0, "10-period momentum is negative"),
                (indicators.rsi_14 < 50, "RSI is below its neutral level"),
                (price < indicators.sma_20, "Price is below SMA 20"),
            )
        return tuple(reason for applies, reason in evidence if applies)
