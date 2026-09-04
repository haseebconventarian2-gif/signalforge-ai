from __future__ import annotations

from decimal import Decimal

import structlog

from app.core.exceptions import BrokerError
from app.domain.broker import BrokerClient
from app.domain.execution import LocalOrderStatus
from app.infrastructure.database.models import OrderRecord
from app.infrastructure.repositories.trading import TradingRepository
from app.services.execution import normalize_order_status

logger = structlog.get_logger(__name__)


class OrderReconciliationService:
    """Reconcile persisted nonterminal intents without ever submitting replacement orders."""

    def __init__(
        self,
        broker: BrokerClient,
        repository: TradingRepository,
        *,
        stop_loss_pct: Decimal,
        take_profit_pct: Decimal,
    ) -> None:
        self._broker = broker
        self._repository = repository
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct

    async def run_once(self) -> int:
        reconciled = 0
        for local in await self._repository.list_reconcilable_orders():
            try:
                provider = await self._broker.get_order_by_client_id(local.client_order_id)
            except BrokerError as exc:
                await logger.awarning(
                    "order_reconciliation_deferred",
                    order_id=str(local.id),
                    error_code=exc.code,
                )
                continue

            previous_filled = local.filled_quantity
            status = normalize_order_status(provider)
            await self._repository.update_order(
                local.id,
                status,
                provider_order_id=provider.id,
                provider_request_id=provider.provider_request_id,
                filled_quantity=provider.filled_qty,
                average_fill_price=provider.filled_avg_price,
            )
            if provider.filled_avg_price is not None and provider.filled_qty > 0:
                if local.intent == "BUY_TO_OPEN":
                    await self._apply_entry_fill(
                        local,
                        filled_quantity=int(provider.filled_qty),
                        average_fill_price=provider.filled_avg_price,
                    )
                else:
                    newly_filled = max(Decimal("0"), provider.filled_qty - previous_filled)
                    await self._apply_close_fill(
                        local.contract_symbol,
                        newly_filled_quantity=int(newly_filled),
                        average_fill_price=provider.filled_avg_price,
                        terminal=status is LocalOrderStatus.FILLED,
                        reason=local.exit_reason or "RECONCILED_EXIT",
                    )
            reconciled += 1
        return reconciled

    async def _apply_entry_fill(
        self,
        local: OrderRecord,
        *,
        filled_quantity: int,
        average_fill_price: Decimal,
    ) -> None:
        selection = await self._repository.get_selection(local.candidate_id)
        if selection is None or selection.contract_symbol != local.contract_symbol:
            await logger.aerror("entry_fill_missing_contract_audit", order_id=str(local.id))
            return
        await self._repository.upsert_position_from_entry_fill(
            local,
            filled_quantity=filled_quantity,
            average_fill_price=average_fill_price,
            expiration_date=selection.expiration_date,
            stop_loss_pct=self._stop_loss_pct,
            take_profit_pct=self._take_profit_pct,
        )

    async def _apply_close_fill(
        self,
        contract_symbol: str,
        *,
        newly_filled_quantity: int,
        average_fill_price: Decimal,
        terminal: bool,
        reason: str,
    ) -> None:
        position = await self._repository.get_open_position(contract_symbol)
        if position is None:
            return
        if newly_filled_quantity <= 0 and not terminal:
            return
        await self._repository.apply_close_fill(
            position,
            newly_filled_quantity=newly_filled_quantity,
            average_fill_price=average_fill_price,
            terminal=terminal,
            reason=reason,
        )
