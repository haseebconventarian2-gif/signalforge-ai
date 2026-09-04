from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator, model_validator

Confidence = Annotated[
    Decimal,
    Field(ge=0, le=1),
    WithJsonSchema({"type": "number", "minimum": 0, "maximum": 1}),
]


class ReasoningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TradeDecision(StrEnum):
    BUY_CALL = "BUY_CALL"
    BUY_PUT = "BUY_PUT"
    NO_TRADE = "NO_TRADE"


class MarketBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class MoneynessPreference(StrEnum):
    ATM = "ATM"
    SLIGHTLY_ITM = "SLIGHTLY_ITM"
    SLIGHTLY_OTM = "SLIGHTLY_OTM"


class TradeRecommendation(ReasoningModel):
    symbol: str = Field(min_length=1, max_length=15, pattern=r"^[A-Z][A-Z0-9.-]*$")
    decision: TradeDecision
    confidence: Confidence
    market_bias: MarketBias
    thesis: str = Field(min_length=20, max_length=1200)
    supporting_factors: tuple[str, ...] = Field(min_length=1, max_length=8)
    risk_factors: tuple[str, ...] = Field(min_length=1, max_length=8)
    preferred_moneyness: MoneynessPreference
    minimum_days_to_expiry: int = Field(ge=1, le=60)
    maximum_days_to_expiry: int = Field(ge=1, le=90)

    @field_validator("supporting_factors", "risk_factors")
    @classmethod
    def validate_factors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value or len(value) > 300 for value in normalized):
            raise ValueError("Factors must contain between 1 and 300 characters")
        return normalized

    @model_validator(mode="after")
    def validate_expiry_window(self) -> TradeRecommendation:
        if self.minimum_days_to_expiry > self.maximum_days_to_expiry:
            raise ValueError("Minimum DTE cannot exceed maximum DTE")
        return self


class ProviderReasoningResult(ReasoningModel):
    recommendation: TradeRecommendation
    response_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class DecisionMetadata(ReasoningModel):
    model: str
    provider_response_id: str | None = None
    prompt_version: str
    schema_version: str
    latency_ms: int = Field(ge=0)
    input_characters: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    validation_status: str
    failure_code: str | None = None


class ReasoningDecision(ReasoningModel):
    id: UUID
    recommendation: TradeRecommendation
    metadata: DecisionMetadata


class LLMReasoningProvider(Protocol):
    async def evaluate(self, candidate_json: str) -> ProviderReasoningResult: ...

    async def close(self) -> None: ...
