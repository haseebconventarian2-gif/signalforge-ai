from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.domain.enums import AgentStatus, JournalSeverity
from app.domain.execution import LocalOrderStatus, TradeIntent
from app.domain.market_intelligence import CandidateOpportunity
from app.domain.options import SelectedOptionContract
from app.domain.risk import RiskDecision
from app.infrastructure.database.models import (
    AIDecisionRecord,
    JournalEvent,
    OptionSelectionRecord,
    OrderRecord,
    PositionRecord,
    PositionSnapshotRecord,
    RiskDecisionRecord,
    SystemControl,
    TradeCandidateRecord,
)


class TradingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_candidate(self, candidate: CandidateOpportunity) -> TradeCandidateRecord:
        record = TradeCandidateRecord(
            correlation_id=uuid4(),
            symbol=candidate.symbol,
            status="DISCOVERED",
            direction=candidate.directional_bias.value,
            signal_score=candidate.signal_score,
            snapshot=candidate.model_dump(mode="json"),
            reasons={"items": list(candidate.reasons)},
            observed_at=candidate.timestamp,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def update_candidate_status(self, candidate_id: UUID, status: str) -> None:
        record = await self.session.get(TradeCandidateRecord, candidate_id)
        if record:
            record.status = status
            await self.session.commit()

    async def save_risk(
        self,
        candidate_id: UUID,
        decision: RiskDecision,
        *,
        contract_symbol: str | None = None,
    ) -> None:
        self.session.add(
            RiskDecisionRecord(
                id=decision.id,
                candidate_id=candidate_id,
                contract_symbol=contract_symbol,
                stage=decision.stage.value,
                verdict=decision.verdict.value,
                evaluations={
                    "items": [item.model_dump(mode="json") for item in decision.evaluations]
                },
                approved_quantity=decision.approved_quantity,
                maximum_capital=decision.maximum_capital,
            )
        )
        await self.session.commit()

    async def save_selection(
        self, candidate_id: UUID, selection: SelectedOptionContract
    ) -> OptionSelectionRecord:
        quote = selection.snapshot.latest_quote
        if quote is None:
            raise ValueError("Selected contract must contain a quote")
        record = OptionSelectionRecord(
            candidate_id=candidate_id,
            contract_symbol=selection.contract.symbol,
            underlying_symbol=selection.contract.underlying_symbol,
            option_type=selection.contract.type.value,
            strike_price=selection.contract.strike_price,
            expiration_date=selection.contract.expiration_date,
            bid=quote.bid_price,
            ask=quote.ask_price,
            midpoint=selection.midpoint,
            spread_percentage=selection.spread_percentage,
            premium=selection.premium_per_contract,
            observed_at=quote.timestamp,
            score=selection.score.model_dump(mode="json"),
            selected=True,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_order_by_client_id(self, client_order_id: str) -> OrderRecord | None:
        result = await self.session.execute(
            select(OrderRecord).where(OrderRecord.client_order_id == client_order_id)
        )
        return result.scalar_one_or_none()

    async def get_order(self, order_id: UUID) -> OrderRecord | None:
        return await self.session.get(OrderRecord, order_id)

    async def create_order_intent(self, intent: TradeIntent) -> OrderRecord:
        existing = await self.get_order_by_client_id(intent.client_order_id)
        if existing:
            return existing
        await self._verify_execution_evidence(intent)
        record = OrderRecord(
            id=intent.id,
            candidate_id=intent.candidate_id,
            client_order_id=intent.client_order_id,
            contract_symbol=intent.contract_symbol,
            underlying_symbol=intent.underlying_symbol,
            intent="BUY_TO_OPEN",
            status=LocalOrderStatus.SUBMITTING.value,
            quantity=intent.quantity,
            filled_quantity=Decimal("0"),
            limit_price=intent.limit_price,
            maximum_loss=intent.maximum_loss,
        )
        self.session.add(record)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_order_by_client_id(intent.client_order_id)
            if existing:
                return existing
            raise
        await self.session.refresh(record)
        return record

    async def _verify_execution_evidence(self, intent: TradeIntent) -> None:
        candidate = await self.session.get(TradeCandidateRecord, intent.candidate_id)
        ai = await self.session.scalar(
            select(AIDecisionRecord)
            .where(
                AIDecisionRecord.candidate_id == intent.candidate_id,
                AIDecisionRecord.validation_status == "validated",
                AIDecisionRecord.decision.in_(["BUY_CALL", "BUY_PUT"]),
            )
            .order_by(AIDecisionRecord.created_at.desc())
            .limit(1)
        )
        risk = await self.session.scalar(
            select(RiskDecisionRecord)
            .where(
                RiskDecisionRecord.candidate_id == intent.candidate_id,
                RiskDecisionRecord.stage == "FINAL",
                RiskDecisionRecord.verdict == "APPROVED",
                RiskDecisionRecord.contract_symbol == intent.contract_symbol,
            )
            .order_by(RiskDecisionRecord.created_at.desc())
            .limit(1)
        )
        selection = await self.session.scalar(
            select(OptionSelectionRecord)
            .where(
                OptionSelectionRecord.candidate_id == intent.candidate_id,
                OptionSelectionRecord.contract_symbol == intent.contract_symbol,
                OptionSelectionRecord.selected.is_(True),
            )
            .limit(1)
        )
        if candidate is None or candidate.symbol != intent.underlying_symbol:
            raise ConflictError("Trade intent does not match its persisted candidate")
        if ai is None:
            raise ConflictError("A validated persisted AI recommendation is required")
        if risk is None:
            raise ConflictError("A persisted final risk approval is required")
        if selection is None:
            raise ConflictError("A persisted Alpaca contract selection is required")
        expected_option_type = "call" if ai.decision == "BUY_CALL" else "put"
        if (
            selection.underlying_symbol != candidate.symbol
            or selection.option_type != expected_option_type
        ):
            raise ConflictError("Persisted AI direction and option contract do not match")
        if risk.approved_quantity < intent.quantity or risk.maximum_capital < intent.maximum_loss:
            raise ConflictError("Trade intent exceeds its persisted risk approval")

    async def update_order(
        self,
        order_id: UUID,
        status: LocalOrderStatus,
        *,
        provider_order_id: UUID | None = None,
        provider_request_id: str | None = None,
        filled_quantity: Decimal | None = None,
        average_fill_price: Decimal | None = None,
    ) -> None:
        record = await self.session.get(OrderRecord, order_id)
        if record is None:
            return
        record.status = status.value
        if provider_order_id:
            record.provider_order_id = provider_order_id
        if provider_request_id:
            record.provider_request_id = provider_request_id
        if filled_quantity is not None:
            record.filled_quantity = filled_quantity
        if average_fill_price is not None:
            record.average_fill_price = average_fill_price
        if status is LocalOrderStatus.SUBMITTED:
            record.submitted_at = datetime.now(UTC)
        await self.session.commit()

    async def create_position(
        self,
        *,
        candidate_id: UUID,
        contract_symbol: str,
        underlying_symbol: str,
        quantity: int,
        entry_price: Decimal,
        expiration_date: date,
        stop_loss_pct: Decimal,
        take_profit_pct: Decimal,
    ) -> PositionRecord:
        existing = (
            await self.session.execute(
                select(PositionRecord).where(
                    PositionRecord.contract_symbol == contract_symbol,
                    PositionRecord.status == "OPEN",
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        record = PositionRecord(
            candidate_id=candidate_id,
            contract_symbol=contract_symbol,
            underlying_symbol=underlying_symbol,
            status="OPEN",
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            stop_price=entry_price * (Decimal("1") - stop_loss_pct),
            target_price=entry_price * (Decimal("1") + take_profit_pct),
            expiration_date=expiration_date,
            opened_at=datetime.now(UTC),
            version=1,
        )
        self.session.add(record)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.get_open_position(contract_symbol)
            if existing:
                return existing
            raise
        await self.session.refresh(record)
        return record

    async def list_open_positions(self) -> tuple[PositionRecord, ...]:
        result = await self.session.execute(
            select(PositionRecord).where(PositionRecord.status == "OPEN")
        )
        return tuple(result.scalars())

    async def risk_state(self, symbol: str) -> dict[str, object]:
        positions = await self.list_open_positions()
        total_exposure = sum(
            (position.entry_price * position.quantity * 100 for position in positions),
            Decimal("0"),
        )
        underlying_exposure = sum(
            (
                position.entry_price * position.quantity * 100
                for position in positions
                if position.underlying_symbol == symbol
            ),
            Decimal("0"),
        )
        closed = tuple(
            (
                await self.session.execute(
                    select(PositionRecord)
                    .where(PositionRecord.status == "CLOSED")
                    .order_by(PositionRecord.closed_at.desc())
                )
            ).scalars()
        )
        today = datetime.now(UTC).date()
        daily_pnl = sum(
            (
                item.realized_pnl or Decimal("0")
                for item in closed
                if item.closed_at and item.closed_at.date() == today
            ),
            Decimal("0"),
        )
        streak = 0
        last_loss_at = None
        for item in closed:
            if item.realized_pnl is None or item.realized_pnl >= 0:
                break
            streak += 1
            last_loss_at = last_loss_at or item.closed_at
        return {
            "total_exposure": total_exposure,
            "underlying_exposure": underlying_exposure,
            "open_position_count": len(positions),
            "daily_pnl": daily_pnl,
            "consecutive_losses": streak,
            "last_loss_at": last_loss_at,
        }

    async def list_candidates(self, limit: int = 100) -> tuple[TradeCandidateRecord, ...]:
        result = await self.session.execute(
            select(TradeCandidateRecord)
            .order_by(TradeCandidateRecord.created_at.desc())
            .limit(limit)
        )
        return tuple(result.scalars())

    async def list_orders(self, limit: int = 100) -> tuple[OrderRecord, ...]:
        result = await self.session.execute(
            select(OrderRecord).order_by(OrderRecord.created_at.desc()).limit(limit)
        )
        return tuple(result.scalars())

    async def list_reconcilable_orders(self) -> tuple[OrderRecord, ...]:
        result = await self.session.execute(
            select(OrderRecord).where(
                OrderRecord.status.in_(
                    [
                        LocalOrderStatus.SUBMITTING.value,
                        LocalOrderStatus.SUBMITTED.value,
                        LocalOrderStatus.PARTIALLY_FILLED.value,
                        LocalOrderStatus.UNKNOWN_RECONCILIATION_REQUIRED.value,
                    ]
                )
            )
        )
        return tuple(result.scalars())

    async def get_selection(self, candidate_id: UUID) -> OptionSelectionRecord | None:
        result = await self.session.scalars(
            select(OptionSelectionRecord)
            .where(
                OptionSelectionRecord.candidate_id == candidate_id,
                OptionSelectionRecord.selected.is_(True),
            )
            .order_by(OptionSelectionRecord.observed_at.desc())
            .limit(1)
        )
        return result.first()

    async def get_open_position(self, contract_symbol: str) -> PositionRecord | None:
        result = await self.session.scalars(
            select(PositionRecord).where(
                PositionRecord.contract_symbol == contract_symbol,
                PositionRecord.status == "OPEN",
            )
        )
        return result.first()

    async def upsert_position_from_entry_fill(
        self,
        order: OrderRecord,
        *,
        filled_quantity: int,
        average_fill_price: Decimal,
        expiration_date: date,
        stop_loss_pct: Decimal,
        take_profit_pct: Decimal,
    ) -> PositionRecord:
        existing = await self.get_open_position(order.contract_symbol)
        if existing:
            existing.quantity = max(existing.quantity, filled_quantity)
            existing.entry_price = average_fill_price
            existing.current_price = average_fill_price
            existing.stop_price = average_fill_price * (Decimal("1") - stop_loss_pct)
            existing.target_price = average_fill_price * (Decimal("1") + take_profit_pct)
            existing.version += 1
            await self.session.commit()
            return existing
        return await self.create_position(
            candidate_id=order.candidate_id,
            contract_symbol=order.contract_symbol,
            underlying_symbol=order.underlying_symbol,
            quantity=filled_quantity,
            entry_price=average_fill_price,
            expiration_date=expiration_date,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )

    async def apply_close_fill(
        self,
        position: PositionRecord,
        *,
        newly_filled_quantity: int,
        average_fill_price: Decimal,
        terminal: bool,
        reason: str,
    ) -> None:
        if terminal or newly_filled_quantity >= position.quantity:
            await self.close_position(position, current_price=average_fill_price, reason=reason)
            return
        position.quantity -= newly_filled_quantity
        position.current_price = average_fill_price
        position.version += 1
        await self.session.commit()

    async def get_control(self) -> SystemControl | None:
        return await self.session.get(SystemControl, 1)

    async def snapshot_position(
        self,
        position: PositionRecord,
        *,
        current_price: Decimal,
        observed_at: datetime,
    ) -> None:
        position.current_price = current_price
        position.version += 1
        self.session.add(
            PositionSnapshotRecord(
                position_id=position.id,
                quantity=position.quantity,
                current_price=current_price,
                unrealized_pnl=(current_price - position.entry_price) * 100 * position.quantity,
                observed_at=observed_at,
            )
        )
        await self.session.commit()

    async def close_position(
        self, position: PositionRecord, *, current_price: Decimal, reason: str
    ) -> None:
        position.status = "CLOSED"
        position.current_price = current_price
        position.closed_at = datetime.now(UTC)
        position.realized_pnl = (current_price - position.entry_price) * 100 * position.quantity
        position.exit_reason = reason
        position.version += 1
        await self.session.commit()

    async def has_active_underlying(self, symbol: str) -> bool:
        positions = await self.session.scalar(
            select(func.count())
            .select_from(PositionRecord)
            .where(PositionRecord.underlying_symbol == symbol, PositionRecord.status == "OPEN")
        )
        orders = await self.session.scalar(
            select(func.count())
            .select_from(OrderRecord)
            .where(
                OrderRecord.underlying_symbol == symbol,
                OrderRecord.status.in_(
                    [
                        LocalOrderStatus.SUBMITTING.value,
                        LocalOrderStatus.SUBMITTED.value,
                        LocalOrderStatus.PARTIALLY_FILLED.value,
                        LocalOrderStatus.UNKNOWN_RECONCILIATION_REQUIRED.value,
                    ]
                ),
            )
        )
        return bool((positions or 0) + (orders or 0))

    async def has_active_close_order(self, contract_symbol: str) -> bool:
        count = await self.session.scalar(
            select(func.count())
            .select_from(OrderRecord)
            .where(
                OrderRecord.contract_symbol == contract_symbol,
                OrderRecord.intent == "SELL_TO_CLOSE",
                OrderRecord.status.in_(
                    [
                        LocalOrderStatus.SUBMITTING.value,
                        LocalOrderStatus.SUBMITTED.value,
                        LocalOrderStatus.PARTIALLY_FILLED.value,
                        LocalOrderStatus.UNKNOWN_RECONCILIATION_REQUIRED.value,
                    ]
                ),
            )
        )
        return bool(count)

    async def create_close_order(
        self,
        position: PositionRecord,
        *,
        current_price: Decimal,
        exit_reason: str,
    ) -> OrderRecord:
        if position.candidate_id is None:
            raise ValueError("A reconciled candidate is required before automated close")
        client_order_id = f"sf-close-{position.id.hex[:28]}"
        existing = await self.get_order_by_client_id(client_order_id)
        if existing:
            return existing
        record = OrderRecord(
            candidate_id=position.candidate_id,
            client_order_id=client_order_id,
            contract_symbol=position.contract_symbol,
            underlying_symbol=position.underlying_symbol,
            intent="SELL_TO_CLOSE",
            status=LocalOrderStatus.SUBMITTING.value,
            quantity=position.quantity,
            filled_quantity=Decimal("0"),
            limit_price=current_price,
            maximum_loss=Decimal("0.01"),
            exit_reason=exit_reason,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def journal(
        self,
        event_type: str,
        message: str,
        *,
        correlation_id: UUID,
        candidate_id: UUID | None = None,
        severity: JournalSeverity = JournalSeverity.INFO,
        details: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            JournalEvent(
                correlation_id=correlation_id,
                candidate_id=candidate_id,
                event_type=event_type,
                severity=severity,
                message=message,
                details=details or {},
            )
        )
        await self.session.commit()

    async def save_control(
        self,
        *,
        desired_state: str,
        kill_switch_active: bool,
        reason: str,
    ) -> None:
        state = AgentStatus(desired_state)
        record = await self.session.get(SystemControl, 1)
        if record is None:
            record = SystemControl(
                id=1,
                desired_state=state,
                kill_switch_active=kill_switch_active,
                changed_by="api",
                reason=reason,
            )
            self.session.add(record)
        else:
            record.desired_state = state
            record.kill_switch_active = kill_switch_active
            record.changed_by = "api"
            record.reason = reason
        await self.session.commit()
