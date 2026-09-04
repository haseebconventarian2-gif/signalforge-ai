from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.exceptions import AmbiguousOrderSubmissionError, BrokerError
from app.domain.broker import BrokerClient, MarketDataProvider
from app.domain.execution import LocalOrderStatus
from app.domain.monitoring import (
    ExitDecision,
    ExitPolicy,
    ExitReason,
    PositionMonitorResult,
    PositionState,
)
from app.infrastructure.database.models import PositionRecord
from app.infrastructure.repositories.trading import TradingRepository


class ExitEngine:
    """Pure exit policy with explicit priority and evidence."""

    def __init__(self, policy: ExitPolicy) -> None:
        self.policy = policy

    def evaluate(
        self,
        position: PositionState,
        *,
        observed_at: datetime,
        kill_switch_active: bool,
    ) -> ExitDecision:
        observed_return = (position.current_price / position.entry_price) - 1
        dte = (position.expiration_date - observed_at.date()).days
        opened_at = position.opened_at
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=UTC)
        holding_days = (observed_at - opened_at).days
        if kill_switch_active:
            return self._exit(
                ExitReason.KILL_SWITCH, observed_return, "Emergency kill switch requires exit"
            )
        if observed_return <= -self.policy.stop_loss_pct:
            return self._exit(
                ExitReason.STOP_LOSS, observed_return, "Position reached deterministic stop loss"
            )
        if observed_return >= self.policy.take_profit_pct:
            return self._exit(
                ExitReason.TAKE_PROFIT,
                observed_return,
                "Position reached deterministic take profit",
            )
        if dte <= self.policy.exit_dte:
            return self._exit(
                ExitReason.EXPIRY, observed_return, "Position is approaching expiration"
            )
        if holding_days >= self.policy.maximum_holding_days:
            return self._exit(
                ExitReason.MAX_HOLD, observed_return, "Maximum holding period reached"
            )
        if position.signal_reversed:
            return self._exit(
                ExitReason.SIGNAL_REVERSAL, observed_return, "Deterministic signal reversed"
            )
        return ExitDecision(
            should_exit=False,
            reason=ExitReason.NONE,
            observed_return=observed_return,
            explanation="No exit threshold was reached",
        )

    @staticmethod
    def _exit(reason: ExitReason, value: Decimal, explanation: str) -> ExitDecision:
        return ExitDecision(
            should_exit=True,
            reason=reason,
            observed_return=value,
            explanation=explanation,
        )


class PositionMonitor:
    """Snapshot local positions and submit at most one guarded paper close."""

    def __init__(
        self,
        broker: BrokerClient,
        market_data: MarketDataProvider,
        repository: TradingRepository,
        exit_engine: ExitEngine,
    ) -> None:
        self._broker = broker
        self._market_data = market_data
        self._repository = repository
        self._exit_engine = exit_engine

    async def run_once(
        self, *, observed_at: datetime | None = None, kill_switch_active: bool = False
    ) -> tuple[PositionMonitorResult, ...]:
        timestamp = observed_at or datetime.now(UTC)
        positions = await self._repository.list_open_positions()
        if not positions:
            return ()
        snapshots = {
            item.symbol: item
            for item in await self._market_data.get_option_snapshots(
                tuple(position.contract_symbol for position in positions)
            )
        }
        results: list[PositionMonitorResult] = []
        for position in positions:
            snapshot = snapshots.get(position.contract_symbol)
            quote = snapshot.latest_quote if snapshot else None
            if quote is None or quote.bid_price < 0:
                continue
            current_price = (quote.bid_price + quote.ask_price) / 2
            await self._repository.snapshot_position(
                position, current_price=current_price, observed_at=timestamp
            )
            decision = self._exit_engine.evaluate(
                PositionState(
                    contract_symbol=position.contract_symbol,
                    underlying_symbol=position.underlying_symbol,
                    quantity=position.quantity,
                    entry_price=position.entry_price,
                    current_price=current_price,
                    opened_at=position.opened_at,
                    expiration_date=position.expiration_date,
                ),
                observed_at=timestamp,
                kill_switch_active=kill_switch_active,
            )
            close_status = None
            if decision.should_exit and not await self._repository.has_active_close_order(
                position.contract_symbol
            ):
                close_status = await self._submit_close(position, current_price, decision)
            results.append(
                PositionMonitorResult(
                    contract_symbol=position.contract_symbol,
                    decision=decision,
                    close_order_status=close_status,
                )
            )
        return tuple(results)

    async def _submit_close(
        self,
        position: PositionRecord,
        current_price: Decimal,
        decision: ExitDecision,
    ) -> str:
        order = await self._repository.create_close_order(
            position,
            current_price=current_price,
            exit_reason=decision.reason.value,
        )
        try:
            provider_order = await self._broker.close_owned_option_position(
                position.contract_symbol,
                position.quantity,
                client_order_id=order.client_order_id,
                limit_price=current_price,
            )
        except AmbiguousOrderSubmissionError as exc:
            status = LocalOrderStatus.UNKNOWN_RECONCILIATION_REQUIRED
            request_id = str(exc.context.get("provider_request_id") or "") or None
            await self._repository.update_order(order.id, status, provider_request_id=request_id)
            return status.value
        except BrokerError:
            status = LocalOrderStatus.REJECTED
            await self._repository.update_order(order.id, status)
            return status.value
        status = (
            LocalOrderStatus.FILLED
            if provider_order.status == "filled"
            else LocalOrderStatus.SUBMITTED
        )
        await self._repository.update_order(
            order.id,
            status,
            provider_order_id=provider_order.id,
            provider_request_id=provider_order.provider_request_id,
            filled_quantity=provider_order.filled_qty,
            average_fill_price=provider_order.filled_avg_price,
        )
        if provider_order.filled_avg_price is not None and provider_order.filled_qty > 0:
            await self._repository.apply_close_fill(
                position,
                newly_filled_quantity=int(provider_order.filled_qty),
                average_fill_price=provider_order.filled_avg_price,
                terminal=status is LocalOrderStatus.FILLED,
                reason=decision.reason.value,
            )
        return status.value
