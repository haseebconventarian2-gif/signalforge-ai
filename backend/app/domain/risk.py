from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.domain.market_intelligence import CandidateOpportunity
from app.domain.reasoning import TradeRecommendation


class RiskModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskStage(StrEnum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"


class RiskVerdict(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskLimits(RiskModel):
    max_risk_per_trade_pct: Decimal = Field(gt=0, le=1)
    max_premium_per_trade: Decimal = Field(gt=0)
    max_portfolio_exposure_pct: Decimal = Field(gt=0, le=1)
    max_open_positions: int = Field(gt=0)
    max_underlying_exposure_pct: Decimal = Field(gt=0, le=1)
    min_ai_confidence: Decimal = Field(ge=0, le=1)
    max_daily_loss_pct: Decimal = Field(gt=0, le=1)
    max_consecutive_losses: int = Field(gt=0)
    cooldown_minutes: int = Field(gt=0)
    max_quote_age_seconds: int = Field(gt=0)
    min_volume_ratio: Decimal = Field(ge=0)
    max_bid_ask_spread_pct: Decimal = Field(gt=0, le=1)
    min_dte: int = Field(gt=0)
    max_dte: int = Field(gt=0)


class RiskContext(RiskModel):
    candidate: CandidateOpportunity
    recommendation: TradeRecommendation
    stage: RiskStage = RiskStage.PRELIMINARY
    observed_at: datetime
    equity: Decimal = Field(gt=0)
    options_buying_power: Decimal = Field(ge=0)
    total_options_exposure: Decimal = Field(ge=0)
    underlying_exposure: Decimal = Field(ge=0)
    open_position_count: int = Field(ge=0)
    daily_realized_pnl: Decimal
    consecutive_losses: int = Field(ge=0)
    cooldown_until: datetime | None = None
    duplicate_trade: bool = False
    market_open: bool
    kill_switch_active: bool = False
    quote_timestamp: datetime | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    dte: int | None = None
    contract_premium: Decimal | None = None


class RiskRuleEvaluation(RiskModel):
    rule_name: str
    passed: bool
    actual_value: str
    limit: str
    reason: str


class RiskDecision(RiskModel):
    id: UUID = Field(default_factory=uuid4)
    verdict: RiskVerdict
    stage: RiskStage
    evaluations: tuple[RiskRuleEvaluation, ...]
    approved_quantity: int = Field(default=0, ge=0)
    maximum_capital: Decimal = Field(default=Decimal("0"), ge=0)
