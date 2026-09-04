from __future__ import annotations

from decimal import Decimal

from app.core.exceptions import IndicatorCalculationError
from app.domain.broker import Bar
from app.domain.market_intelligence import IndicatorSnapshot


class IndicatorEngine:
    """Calculate deterministic daily indicators from chronological OHLCV bars."""

    minimum_bars = 60

    def calculate(self, bars: tuple[Bar, ...]) -> IndicatorSnapshot:
        ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
        if len(ordered) < self.minimum_bars:
            raise IndicatorCalculationError(
                f"At least {self.minimum_bars} bars are required",
                context={"bars_received": len(ordered)},
            )
        if len({bar.timestamp for bar in ordered}) != len(ordered):
            raise IndicatorCalculationError("Bar timestamps must be unique")
        if any(bar.close <= 0 or bar.high < bar.low or bar.volume < 0 for bar in ordered):
            raise IndicatorCalculationError("Bars contain invalid price or volume values")

        closes = tuple(bar.close for bar in ordered)
        volumes = tuple(bar.volume for bar in ordered)
        ema_12_series = self._ema_series(closes, 12)
        ema_26_series = self._ema_series(closes, 26)
        macd_series = tuple(
            fast - slow for fast, slow in zip(ema_12_series, ema_26_series, strict=True)
        )
        macd_signal_series = self._ema_series(macd_series, 9)
        ema_20 = self._ema_series(closes, 20)[-1]
        ema_50 = self._ema_series(closes, 50)[-1]
        atr = self._atr(ordered, 14)

        return IndicatorSnapshot(
            period_return=(closes[-1] / closes[-2]) - 1,
            sma_20=self._mean(closes[-20:]),
            ema_20=ema_20,
            ema_50=ema_50,
            rsi_14=self._rsi(closes, 14),
            macd=macd_series[-1],
            macd_signal=macd_signal_series[-1],
            macd_histogram=macd_series[-1] - macd_signal_series[-1],
            atr_14=atr,
            volume_ratio_20=self._volume_ratio(volumes, 20),
            annualized_volatility_20=self._annualized_volatility(closes, 20),
            recent_high_20=max(bar.high for bar in ordered[-20:]),
            recent_low_20=min(bar.low for bar in ordered[-20:]),
            momentum_10=(closes[-1] / closes[-11]) - 1,
            trend_strength=abs(ema_20 - ema_50) / atr if atr > 0 else Decimal("0"),
        )

    @staticmethod
    def _mean(values: tuple[Decimal, ...]) -> Decimal:
        return sum(values, Decimal("0")) / Decimal(len(values))

    @staticmethod
    def _ema_series(values: tuple[Decimal, ...], period: int) -> tuple[Decimal, ...]:
        alpha = Decimal(2) / Decimal(period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append((alpha * value) + ((Decimal("1") - alpha) * result[-1]))
        return tuple(result)

    @classmethod
    def _rsi(cls, closes: tuple[Decimal, ...], period: int) -> Decimal:
        changes = tuple(
            current - previous for previous, current in zip(closes, closes[1:], strict=False)
        )
        gains = tuple(max(change, Decimal("0")) for change in changes)
        losses = tuple(max(-change, Decimal("0")) for change in changes)
        average_gain = cls._mean(gains[:period])
        average_loss = cls._mean(losses[:period])
        for gain, loss in zip(gains[period:], losses[period:], strict=True):
            average_gain = ((average_gain * (period - 1)) + gain) / period
            average_loss = ((average_loss * (period - 1)) + loss) / period
        if average_gain == 0 and average_loss == 0:
            return Decimal("50")
        if average_loss == 0:
            return Decimal("100")
        relative_strength = average_gain / average_loss
        return Decimal("100") - (Decimal("100") / (Decimal("1") + relative_strength))

    @classmethod
    def _atr(cls, bars: tuple[Bar, ...], period: int) -> Decimal:
        true_ranges = tuple(
            max(
                bar.high - bar.low,
                abs(bar.high - previous.close),
                abs(bar.low - previous.close),
            )
            for previous, bar in zip(bars, bars[1:], strict=False)
        )
        average = cls._mean(true_ranges[:period])
        for true_range in true_ranges[period:]:
            average = ((average * (period - 1)) + true_range) / period
        return average

    @classmethod
    def _volume_ratio(cls, volumes: tuple[Decimal, ...], period: int) -> Decimal:
        baseline = cls._mean(volumes[-period - 1 : -1])
        return volumes[-1] / baseline if baseline > 0 else Decimal("0")

    @classmethod
    def _annualized_volatility(cls, closes: tuple[Decimal, ...], period: int) -> Decimal:
        log_returns = tuple(
            (current / previous).ln() for previous, current in zip(closes, closes[1:], strict=False)
        )
        sample = log_returns[-period:]
        average = cls._mean(sample)
        variance = sum((value - average) ** 2 for value in sample) / Decimal(period - 1)
        return variance.sqrt() * Decimal(252).sqrt()
