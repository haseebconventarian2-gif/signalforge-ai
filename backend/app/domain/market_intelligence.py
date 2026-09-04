from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.broker import Bar


class MarketIntelligenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DirectionalBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class IndicatorSnapshot(MarketIntelligenceModel):
    period_return: Decimal
    sma_20: Decimal
    ema_20: Decimal
    ema_50: Decimal
    rsi_14: Decimal = Field(ge=0, le=100)
    macd: Decimal
    macd_signal: Decimal
    macd_histogram: Decimal
    atr_14: Decimal = Field(ge=0)
    volume_ratio_20: Decimal = Field(ge=0)
    annualized_volatility_20: Decimal = Field(ge=0)
    recent_high_20: Decimal
    recent_low_20: Decimal
    momentum_10: Decimal
    trend_strength: Decimal = Field(ge=0)


class MarketSeries(MarketIntelligenceModel):
    symbol: str
    bars: tuple[Bar, ...]
    underlying_price: Decimal = Field(gt=0)
    data_timestamp: datetime


class CandidateOpportunity(MarketIntelligenceModel):
    symbol: str
    timestamp: datetime
    data_timestamp: datetime
    underlying_price: Decimal = Field(gt=0)
    directional_bias: DirectionalBias
    signal_score: Decimal = Field(ge=0, le=1)
    indicator_snapshot: IndicatorSnapshot
    reasons: tuple[str, ...]
    data_freshness_seconds: int = Field(ge=0)


class MarketScanResult(MarketIntelligenceModel):
    timestamp: datetime
    watchlist: tuple[str, ...]
    opportunities: tuple[CandidateOpportunity, ...]
    market_open: bool | None = None
