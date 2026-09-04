from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.exceptions import AmbiguousOrderSubmissionError, ConflictError
from app.domain.broker import (
    BrokerOrder,
    MarketClock,
    OptionSnapshot,
    OrderSide,
    OrderType,
    Quote,
)
from app.domain.execution import LocalOrderStatus
from app.domain.reasoning import TradeRecommendation
from app.domain.risk import RiskDecision, RiskStage, RiskVerdict
from app.infrastructure.database.models import AIDecisionRecord, OptionSelectionRecord
from app.infrastructure.repositories.trading import TradingRepository
from app.services.execution import ExecutionService
from tests.unit.test_option_selector import contract, selector, snapshot
from tests.unit.test_reasoning_models import valid_recommendation
from tests.unit.test_reasoning_service import candidate

NOW = datetime(2026, 9, 4, 16, tzinfo=UTC)


class FakeBroker:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.ambiguous = ambiguous
        self.submissions = 0

    async def get_market_clock(self) -> MarketClock:
        return MarketClock(timestamp=NOW, is_open=True, next_open=NOW, next_close=NOW)

    async def submit_order(self, intent):
        self.submissions += 1
        if self.ambiguous:
            raise AmbiguousOrderSubmissionError("unknown")
        return BrokerOrder(
            id=uuid4(),
            client_order_id=intent.client_order_id,
            status="new",
            symbol=intent.symbol,
            qty=Decimal(intent.quantity),
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            time_in_force="day",
            created_at=NOW,
        )

    async def get_order_by_client_id(self, client_order_id):  # pragma: no cover
        raise NotImplementedError

    async def close(self):  # pragma: no cover
        return None


class FakeMarketData:
    async def get_option_snapshots(self, symbols):
        return (
            OptionSnapshot(
                symbol=symbols[0],
                latest_quote=Quote(
                    timestamp=NOW,
                    bid_price=Decimal("4.90"),
                    ask_price=Decimal("5.10"),
                    bid_size=Decimal("10"),
                    ask_size=Decimal("10"),
                ),
            ),
        )

    async def close(self):  # pragma: no cover
        return None


def risk() -> RiskDecision:
    return RiskDecision(
        verdict=RiskVerdict.APPROVED,
        stage=RiskStage.FINAL,
        evaluations=(),
        approved_quantity=1,
        maximum_capital=Decimal("750"),
    )


async def make_selection():
    item = contract("SPY_OPT", "103")
    result = selector().select(
        candidate(),
        TradeRecommendation.model_validate(valid_recommendation()),
        (item,),
        (snapshot("SPY_OPT", "4.90", "5.10"),),
        as_of=NOW.date(),
        maximum_capital=Decimal("750"),
    )
    assert result.selected is not None
    return result.selected


async def persist_execution_evidence(
    repository: TradingRepository, candidate_id, selection
) -> None:
    recommendation = TradeRecommendation.model_validate(valid_recommendation())
    repository.session.add(
        AIDecisionRecord(
            symbol="SPY",
            candidate_id=candidate_id,
            candidate_fingerprint="a" * 64,
            decision="BUY_CALL",
            confidence=Decimal("0.9"),
            candidate_snapshot=candidate().model_dump(mode="json"),
            recommendation=recommendation.model_dump(mode="json"),
            model="test-model",
            prompt_version="test-v1",
            schema_version="test-v1",
            latency_ms=1,
            input_characters=100,
            validation_status="validated",
        )
    )
    await repository.session.commit()
    await repository.save_selection(candidate_id, selection)
    await repository.save_risk(candidate_id, risk(), contract_symbol=selection.contract.symbol)


async def test_execution_persists_before_submission_and_is_idempotent(database) -> None:
    broker = FakeBroker()
    async with database.session_factory() as session:
        repository = TradingRepository(session)
        candidate_record = await repository.create_candidate(candidate())
        selected = await make_selection()
        await persist_execution_evidence(repository, candidate_record.id, selected)
        service = ExecutionService(
            broker,
            FakeMarketData(),
            repository,
            maximum_quote_age_seconds=15,
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
        )
        first = await service.execute(candidate_record.id, candidate(), risk(), selected)
        second = await service.execute(candidate_record.id, candidate(), risk(), selected)

    assert first.status is LocalOrderStatus.SUBMITTED
    assert second.status is LocalOrderStatus.SUBMITTED
    assert broker.submissions == 1


async def test_ambiguous_submission_is_never_retried(database) -> None:
    broker = FakeBroker(ambiguous=True)
    async with database.session_factory() as session:
        repository = TradingRepository(session)
        candidate_record = await repository.create_candidate(candidate())
        selected = await make_selection()
        await persist_execution_evidence(repository, candidate_record.id, selected)
        service = ExecutionService(
            broker,
            FakeMarketData(),
            repository,
            maximum_quote_age_seconds=15,
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
        )
        result = await service.execute(candidate_record.id, candidate(), risk(), selected)

    assert result.status is LocalOrderStatus.UNKNOWN_RECONCILIATION_REQUIRED
    assert broker.submissions == 1


async def test_execution_rejects_unpersisted_approval_chain(database) -> None:
    broker = FakeBroker()
    async with database.session_factory() as session:
        repository = TradingRepository(session)
        candidate_record = await repository.create_candidate(candidate())
        service = ExecutionService(
            broker,
            FakeMarketData(),
            repository,
            maximum_quote_age_seconds=15,
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
        )

        with pytest.raises(ConflictError, match="persisted AI recommendation"):
            await service.execute(candidate_record.id, candidate(), risk(), await make_selection())

    assert broker.submissions == 0


async def test_database_failure_before_intent_commit_prevents_submission(
    database, monkeypatch: pytest.MonkeyPatch
) -> None:
    broker = FakeBroker()
    async with database.session_factory() as session:
        repository = TradingRepository(session)
        candidate_record = await repository.create_candidate(candidate())
        selected = await make_selection()
        await persist_execution_evidence(repository, candidate_record.id, selected)

        async def fail_before_commit(intent):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(repository, "create_order_intent", fail_before_commit)
        service = ExecutionService(
            broker,
            FakeMarketData(),
            repository,
            maximum_quote_age_seconds=15,
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
        )

        with pytest.raises(RuntimeError, match="database unavailable"):
            await service.execute(candidate_record.id, candidate(), risk(), selected)

    assert broker.submissions == 0


async def test_persisted_contract_direction_must_match_ai_recommendation(database) -> None:
    broker = FakeBroker()
    async with database.session_factory() as session:
        repository = TradingRepository(session)
        candidate_record = await repository.create_candidate(candidate())
        selected = await make_selection()
        await persist_execution_evidence(repository, candidate_record.id, selected)
        selection_record = (
            await session.scalars(
                select(OptionSelectionRecord).where(
                    OptionSelectionRecord.candidate_id == candidate_record.id
                )
            )
        ).one()
        selection_record.option_type = "put"
        await session.commit()
        service = ExecutionService(
            broker,
            FakeMarketData(),
            repository,
            maximum_quote_age_seconds=15,
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
        )

        with pytest.raises(ConflictError, match="direction and option contract"):
            await service.execute(candidate_record.id, candidate(), risk(), selected)

    assert broker.submissions == 0
