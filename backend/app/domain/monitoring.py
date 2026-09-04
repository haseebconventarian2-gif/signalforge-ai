from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MonitoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExitReason(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MAX_HOLD = "MAX_HOLD"
    EXPIRY = "EXPIRY"
    SIGNAL_REVERSAL = "SIGNAL_REVERSAL"
    KILL_SWITCH = "KILL_SWITCH"
    NONE = "NONE"


class PositionState(MonitoringModel):
    contract_symbol: str
    underlying_symbol: str
    quantity: int = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    current_price: Decimal = Field(ge=0)
    opened_at: datetime
    expiration_date: date
    signal_reversed: bool = False


class ExitPolicy(MonitoringModel):
    stop_loss_pct: Decimal = Field(gt=0, le=1)
    take_profit_pct: Decimal = Field(gt=0)
    maximum_holding_days: int = Field(gt=0)
    exit_dte: int = Field(ge=0)


class ExitDecision(MonitoringModel):
    should_exit: bool
    reason: ExitReason
    observed_return: Decimal
    explanation: str


class PositionMonitorResult(MonitoringModel):
    contract_symbol: str
    decision: ExitDecision
    close_order_status: str | None = None
