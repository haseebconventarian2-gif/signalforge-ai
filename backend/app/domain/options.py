from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.broker import OptionContract, OptionSnapshot


class OptionSelectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContractScore(OptionSelectionModel):
    symbol: str
    total: Decimal = Field(ge=0, le=100)
    moneyness_score: Decimal = Field(ge=0, le=35)
    liquidity_score: Decimal = Field(ge=0, le=30)
    spread_score: Decimal = Field(ge=0, le=25)
    expiry_score: Decimal = Field(ge=0, le=10)
    explanation: tuple[str, ...]


class SelectedOptionContract(OptionSelectionModel):
    contract: OptionContract
    snapshot: OptionSnapshot
    midpoint: Decimal = Field(gt=0)
    spread_percentage: Decimal = Field(ge=0)
    premium_per_contract: Decimal = Field(gt=0)
    days_to_expiry: int = Field(gt=0)
    score: ContractScore


class ContractSelectionResult(OptionSelectionModel):
    selected: SelectedOptionContract | None = None
    rejected_contracts: int = Field(ge=0)
    reason: str
