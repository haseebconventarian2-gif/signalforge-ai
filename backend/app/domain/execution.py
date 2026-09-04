from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LocalOrderStatus(StrEnum):
    INTENT_CREATED = "INTENT_CREATED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN_RECONCILIATION_REQUIRED = "UNKNOWN_RECONCILIATION_REQUIRED"


class TradeIntent(ExecutionModel):
    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    contract_symbol: str
    underlying_symbol: str
    quantity: int = Field(gt=0)
    limit_price: Decimal = Field(gt=0)
    maximum_loss: Decimal = Field(gt=0)
    client_order_id: str = Field(min_length=1, max_length=48)
    created_at: datetime


class ExecutionResult(ExecutionModel):
    intent: TradeIntent
    status: LocalOrderStatus
    provider_order_id: UUID | None = None
    provider_request_id: str | None = None
    message: str
