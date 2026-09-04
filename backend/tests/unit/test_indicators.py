from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.exceptions import IndicatorCalculationError
from app.domain.broker import Bar
from app.services.indicators import IndicatorEngine


def make_bars(closes: list[Decimal], *, final_volume: Decimal = Decimal("100")) -> tuple[Bar, ...]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return tuple(
        Bar(
            symbol="SPY",
            timestamp=start + timedelta(days=index),
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=final_volume if index == len(closes) - 1 else Decimal("100"),
        )
        for index, close in enumerate(closes)
    )


def test_flat_series_has_exact_neutral_indicators() -> None:
    result = IndicatorEngine().calculate(
        make_bars([Decimal("100")] * 60, final_volume=Decimal("200"))
    )

    assert result.period_return == 0
    assert result.sma_20 == 100
    assert result.ema_20 == 100
    assert result.ema_50 == 100
    assert result.rsi_14 == 50
    assert result.macd == 0
    assert result.macd_signal == 0
    assert result.macd_histogram == 0
    assert result.atr_14 == 2
    assert result.volume_ratio_20 == 2
    assert result.annualized_volatility_20 == 0
    assert result.recent_high_20 == 101
    assert result.recent_low_20 == 99
    assert result.momentum_10 == 0
    assert result.trend_strength == 0


def test_monotonic_rising_series_has_known_directional_values() -> None:
    closes = [Decimal(100 + index) for index in range(60)]
    result = IndicatorEngine().calculate(make_bars(closes))

    assert result.period_return.quantize(Decimal("0.00000001")) == Decimal("0.00632911")
    assert result.sma_20 == Decimal("149.5")
    assert result.rsi_14 == 100
    assert result.atr_14 == 2
    assert result.recent_high_20 == 160
    assert result.recent_low_20 == 139
    assert result.momentum_10.quantize(Decimal("0.00000001")) == Decimal("0.06711409")
    assert result.ema_20 > result.ema_50
    assert result.macd > 0
    assert result.trend_strength > 0


def test_insufficient_or_invalid_bars_fail_explicitly() -> None:
    engine = IndicatorEngine()

    with pytest.raises(IndicatorCalculationError, match="At least 60 bars"):
        engine.calculate(make_bars([Decimal("100")] * 59))

    invalid = list(make_bars([Decimal("100")] * 60))
    invalid[-1] = invalid[-1].model_copy(update={"close": Decimal("0")})
    with pytest.raises(IndicatorCalculationError, match="invalid price"):
        engine.calculate(tuple(invalid))
