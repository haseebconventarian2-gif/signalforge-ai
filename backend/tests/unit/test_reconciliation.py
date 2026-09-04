from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.core.exceptions import AmbiguousOrderSubmissionError
from app.domain.broker import BrokerOrder, OptionSnapshot, OrderSide, OrderType, Quote
from app.domain.execution import LocalOrderStatus
from app.domain.monitoring import ExitPolicy
from app.infrastructure.repositories.trading import TradingRepository
from app.services.execution import ExecutionService
from app.services.monitoring import ExitEngine, PositionMonitor
from app.services.reconciliation import OrderReconciliationService
from tests.unit.test_execution_service import (
    NOW,
    FakeBroker,
    FakeMarketData,
    make_selection,
    persist_execution_evidence,
    risk,
)
from tests.unit.test_reasoning_service import candidate


class FilledOrderLookupBroker:
    async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder:
        return BrokerOrder(
            id=uuid4(),
            client_order_id=client_order_id,
            status="filled",
            symbol="SPY_OPT",
            asset_class="us_option",
            qty=Decimal("1"),
            filled_qty=Decimal("1"),
            filled_avg_price=Decimal("5.00"),
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            time_in_force="day",
            created_at=NOW,
            filled_at=NOW,
            provider_request_id="reconcile-request",
        )


async def test_restart_reconciliation_creates_position_without_resubmission(database) -> None:
    async with database.session_factory() as session:
        repository = TradingRepository(session)
        candidate_record = await repository.create_candidate(candidate())
        selected = await make_selection()
        await persist_execution_evidence(repository, candidate_record.id, selected)
        await ExecutionService(
            FakeBroker(),
            FakeMarketData(),
            repository,
            maximum_quote_age_seconds=15,
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
        ).execute(candidate_record.id, candidate(), risk(), selected)

        service = OrderReconciliationService(
            FilledOrderLookupBroker(),  # type: ignore[arg-type]
            repository,
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
        )
        assert await service.run_once() == 1
        assert await service.run_once() == 0

        orders = await repository.list_orders()
        positions = await repository.list_open_positions()
        assert orders[0].status == LocalOrderStatus.FILLED.value
        assert orders[0].provider_request_id == "reconcile-request"
        assert len(positions) == 1
        assert positions[0].contract_symbol == "SPY_OPT"
        assert positions[0].quantity == 1


class AmbiguousCloseBroker:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close_owned_option_position(self, *args, **kwargs) -> BrokerOrder:
        self.close_calls += 1
        raise AmbiguousOrderSubmissionError("unknown close state")


class StopQuoteData:
    async def get_option_snapshots(self, symbols: tuple[str, ...]) -> tuple[OptionSnapshot, ...]:
        return (
            OptionSnapshot(
                symbol=symbols[0],
                latest_quote=Quote(
                    timestamp=NOW,
                    bid_price=Decimal("3.20"),
                    ask_price=Decimal("3.30"),
                    bid_size=Decimal("10"),
                    ask_size=Decimal("10"),
                ),
            ),
        )


async def test_ambiguous_close_is_persisted_and_never_resubmitted(database) -> None:
    broker = AmbiguousCloseBroker()
    async with database.session_factory() as session:
        repository = TradingRepository(session)
        candidate_record = await repository.create_candidate(candidate())
        await repository.create_position(
            candidate_id=candidate_record.id,
            contract_symbol="SPY_OPT",
            underlying_symbol="SPY",
            quantity=1,
            entry_price=Decimal("5.00"),
            expiration_date=date(2026, 9, 25),
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
        )
        monitor = PositionMonitor(
            broker,  # type: ignore[arg-type]
            StopQuoteData(),  # type: ignore[arg-type]
            repository,
            ExitEngine(
                ExitPolicy(
                    stop_loss_pct=Decimal("0.35"),
                    take_profit_pct=Decimal("0.60"),
                    maximum_holding_days=10,
                    exit_dte=2,
                )
            ),
        )

        await monitor.run_once(observed_at=NOW)
        await monitor.run_once(observed_at=NOW)

        orders = await repository.list_orders()
        assert broker.close_calls == 1
        assert len(orders) == 1
        assert orders[0].status == LocalOrderStatus.UNKNOWN_RECONCILIATION_REQUIRED.value
        assert orders[0].exit_reason == "STOP_LOSS"
