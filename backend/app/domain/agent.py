from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class AgentCycleState(StrEnum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    CANDIDATE_FOUND = "CANDIDATE_FOUND"
    AI_ANALYSIS = "AI_ANALYSIS"
    RISK_EVALUATION = "RISK_EVALUATION"
    CONTRACT_SELECTION = "CONTRACT_SELECTION"
    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    MONITORING = "MONITORING"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class AgentRuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    desired_state: str
    effective_state: str
    cycle_state: AgentCycleState
    paper_trading: bool = True
    execution_enabled: bool
    autonomy_enabled: bool
    kill_switch_active: bool
    running_cycle: bool
    last_heartbeat: datetime | None = None
    last_error: str | None = None
