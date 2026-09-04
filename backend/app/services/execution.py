from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from app.core.exceptions import AmbiguousOrderSubmissionError, BrokerError, ConflictError
from app.domain.broker import (
    BrokerClient,
    BrokerOrder,
    MarketDataProvider,
    OrderSide,
    OrderType,
    PaperOrderIntent,
    PositionIntent,
)
from app.domain.execution import ExecutionResult, LocalOrderStatus, TradeIntent
from app.domain.market_intelligence import CandidateOpportunity
from app.domain.options import SelectedOptionContract
from app.domain.risk import RiskDecision, RiskStage, RiskVerdict
from app.infrastructure.repositories.trading import TradingRepository


def normalize_order_status(order: BrokerOrder) -> LocalOrderStatus:
    mapping = {
        "filled": LocalOrderStatus.FILLED,
        "partially_filled": LocalOrderStatus.PARTIALLY_FILLED,
        "canceled": LocalOrderStatus.CANCELLED,
        "expired": LocalOrderStatus.CANCELLED,
        "rejected": LocalOrderStatus.REJECTED,
    }
    return mapping.get(order.status, LocalOrderStatus.SUBMITTED)


class ExecutionService:
    """Persist-first, idempotent paper option execution and reconciliation."""

    def __init__(
        self,
        broker: BrokerClient,
        market_data: MarketDataProvider,
        repository: TradingRepository,
        *,
        maximum_quote_age_seconds: int,
        stop_loss_pct: Decimal,
        take_profit_pct: Decimal,
    ) -> None:
        self._broker = broker
        self._market_data = market_data
        self._repository = repository
        self._maximum_quote_age_seconds = maximum_quote_age_seconds
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct

    async def execute(
        self,
        candidate_id: UUID,
        candidate: CandidateOpportunity,
        risk: RiskDecision,
        selection: SelectedOptionContract,
        *,
        attempt: int = 1,
    ) -> ExecutionResult:
        if risk.stage is not RiskStage.FINAL or risk.verdict is not RiskVerdict.APPROVED:
            raise ConflictError("A final approved risk decision is required before execution")
        if risk.approved_quantity <= 0:
            raise ConflictError("Risk engine approved zero contracts")
        clock = await self._broker.get_market_clock()
        if not clock.is_open:
            raise ConflictError("Market closed during final execution validation")
        refreshed = await self._market_data.get_option_snapshots((selection.contract.symbol,))
        snapshot = next(
            (item for item in refreshed if item.symbol == selection.contract.symbol), None
        )
        if snapshot is None or snapshot.latest_quote is None:
            raise ConflictError("Selected option quote is unavailable during final validation")
        quote = snapshot.latest_quote
        age = max(0, int((clock.timestamp - quote.timestamp).total_seconds()))
        if age > self._maximum_quote_age_seconds:
            raise ConflictError("Selected option quote became stale before execution")
        if quote.ask_price <= quote.bid_price or quote.bid_price <= 0:
            raise ConflictError("Selected option quote is invalid")

        limit_price = ((quote.bid_price + quote.ask_price) / 2).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        client_order_id = f"sf-{candidate_id.hex[:28]}-{attempt}"
        maximum_loss = limit_price * 100 * risk.approved_quantity
        intent = TradeIntent(
            candidate_id=candidate_id,
            contract_symbol=selection.contract.symbol,
            underlying_symbol=candidate.symbol,
            quantity=risk.approved_quantity,
            limit_price=limit_price,
            maximum_loss=maximum_loss,
            client_order_id=client_order_id,
            created_at=datetime.now(UTC),
        )
        existing = await self._repository.get_order_by_client_id(client_order_id)
        if existing:
            return ExecutionResult(
                intent=intent.model_copy(update={"id": existing.id}),
                status=LocalOrderStatus(existing.status),
                provider_order_id=existing.provider_order_id,
                provider_request_id=existing.provider_request_id,
                message="Existing idempotent order returned without resubmission",
            )
        await self._repository.create_order_intent(intent)
        paper_intent = PaperOrderIntent(
            symbol=intent.contract_symbol,
            quantity=intent.quantity,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            position_intent=PositionIntent.BUY_TO_OPEN,
            client_order_id=intent.client_order_id,
            limit_price=intent.limit_price,
        )
        try:
            broker_order = await self._broker.submit_order(paper_intent)
        except AmbiguousOrderSubmissionError as exc:
            request_id = str(exc.context.get("provider_request_id") or "") or None
            await self._repository.update_order(
                intent.id,
                LocalOrderStatus.UNKNOWN_RECONCILIATION_REQUIRED,
                provider_request_id=request_id,
            )
            return ExecutionResult(
                intent=intent,
                status=LocalOrderStatus.UNKNOWN_RECONCILIATION_REQUIRED,
                provider_request_id=request_id,
                message="Submission outcome is ambiguous; reconciliation is required",
            )
        except BrokerError as exc:
            await self._repository.update_order(intent.id, LocalOrderStatus.REJECTED)
            return ExecutionResult(
                intent=intent,
                status=LocalOrderStatus.REJECTED,
                provider_request_id=str(exc.context.get("provider_request_id") or "") or None,
                message="Paper broker rejected the persisted order intent",
            )
        status = normalize_order_status(broker_order)
        await self._repository.update_order(
            intent.id,
            status,
            provider_order_id=broker_order.id,
            provider_request_id=broker_order.provider_request_id,
            filled_quantity=broker_order.filled_qty,
            average_fill_price=broker_order.filled_avg_price,
        )
        if status is LocalOrderStatus.FILLED and broker_order.filled_avg_price is not None:
            await self._repository.create_position(
                candidate_id=candidate_id,
                contract_symbol=selection.contract.symbol,
                underlying_symbol=candidate.symbol,
                quantity=int(broker_order.filled_qty),
                entry_price=broker_order.filled_avg_price,
                expiration_date=selection.contract.expiration_date,
                stop_loss_pct=self._stop_loss_pct,
                take_profit_pct=self._take_profit_pct,
            )
        return ExecutionResult(
            intent=intent,
            status=status,
            provider_order_id=broker_order.id,
            provider_request_id=broker_order.provider_request_id,
            message="Paper order response persisted",
        )

    async def reconcile(self, order_id: UUID) -> ExecutionResult:
        local = await self._repository.get_order(order_id)
        if local is None:
            raise ConflictError("Local order does not exist")
        provider_order = await self._broker.get_order_by_client_id(local.client_order_id)
        status = normalize_order_status(provider_order)
        await self._repository.update_order(
            local.id,
            status,
            provider_order_id=provider_order.id,
            provider_request_id=provider_order.provider_request_id,
            filled_quantity=provider_order.filled_qty,
            average_fill_price=provider_order.filled_avg_price,
        )
        intent = TradeIntent(
            id=local.id,
            candidate_id=local.candidate_id,
            contract_symbol=local.contract_symbol,
            underlying_symbol=local.underlying_symbol,
            quantity=local.quantity,
            limit_price=local.limit_price,
            maximum_loss=local.maximum_loss,
            client_order_id=local.client_order_id,
            created_at=local.created_at,
        )
        return ExecutionResult(
            intent=intent,
            status=status,
            provider_order_id=provider_order.id,
            provider_request_id=provider_order.provider_request_id,
            message="Order reconciled by client order ID",
        )
