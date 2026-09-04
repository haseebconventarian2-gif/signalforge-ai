from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import AgentRunStatus, AgentStatus, JournalSeverity, RunTrigger
from app.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def enum_column(enum_type: type, name: str) -> Enum:
    return Enum(enum_type, name=name, native_enum=False, validate_strings=True, length=32)


class AgentConfiguration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_configurations"

    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    strategy: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    risk: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)

    runs: Mapped[list[AgentRun]] = relationship(back_populates="configuration")


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"

    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_configurations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[AgentRunStatus] = mapped_column(
        enum_column(AgentRunStatus, "agent_run_status"), nullable=False
    )
    trigger: Mapped[RunTrigger] = mapped_column(
        enum_column(RunTrigger, "agent_run_trigger"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidates_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates_approved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    orders_submitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))

    configuration: Mapped[AgentConfiguration] = relationship(back_populates="runs")
    journal_events: Mapped[list[JournalEvent]] = relationship(back_populates="run")


class SystemControl(TimestampMixin, Base):
    __tablename__ = "system_controls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    desired_state: Mapped[AgentStatus] = mapped_column(
        enum_column(AgentStatus, "agent_status"), nullable=False, default=AgentStatus.STOPPED
    )
    kill_switch_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    changed_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    reason: Mapped[str | None] = mapped_column(String(500))


class JournalEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "journal_events"
    __table_args__ = (
        Index("ix_journal_events_created_at", "created_at"),
        Index("ix_journal_events_correlation_id", "correlation_id"),
    )

    correlation_id: Mapped[UUID]
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trade_candidates.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[JournalSeverity] = mapped_column(
        enum_column(JournalSeverity, "journal_severity"), nullable=False
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[AgentRun | None] = relationship(back_populates="journal_events")


class AIDecisionRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_decisions"
    __table_args__ = (
        Index("ix_ai_decisions_symbol_created_at", "symbol", "created_at"),
        Index("ix_ai_decisions_candidate_fingerprint", "candidate_fingerprint"),
    )

    symbol: Mapped[str] = mapped_column(String(15), nullable=False)
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trade_candidates.id", ondelete="SET NULL"), index=True
    )
    candidate_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    candidate_snapshot: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    recommendation: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_response_id: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_characters: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TradeCandidateRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trade_candidates"

    correlation_id: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    signal_score: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    reasons: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RiskDecisionRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "risk_decisions"

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("trade_candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_symbol: Mapped[str | None] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluations: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    approved_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_capital: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OptionSelectionRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "option_contract_snapshots"

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("trade_candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    underlying_symbol: Mapped[str] = mapped_column(String(15), nullable=False)
    option_type: Mapped[str] = mapped_column(String(8), nullable=False)
    strike_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    bid: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    ask: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    midpoint: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    spread_percentage: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    premium: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OrderRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),)

    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("trade_candidates.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    client_order_id: Mapped[str] = mapped_column(String(48), nullable=False)
    provider_order_id: Mapped[UUID | None] = mapped_column(unique=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    contract_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    underlying_symbol: Mapped[str] = mapped_column(String(15), nullable=False)
    intent: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    limit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    maximum_loss: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FillRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fills"

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_fill_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(nullable=False)


class PositionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "positions"
    __table_args__ = (
        Index(
            "uq_positions_open_contract",
            "contract_symbol",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
    )

    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trade_candidates.id", ondelete="SET NULL"), index=True
    )
    contract_symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    underlying_symbol: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    stop_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    target_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PositionSnapshotRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "position_snapshots"

    position_id: Mapped[UUID] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortfolioSnapshotRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "portfolio_snapshots"

    equity: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    buying_power: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    options_buying_power: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    options_exposure: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    daily_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    total_pnl: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
