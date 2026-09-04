from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.core.config import Environment, Settings
from app.domain.agent import AgentCycleState
from app.domain.broker import (
    AccountSnapshot,
    BrokerOrder,
    BrokerPosition,
    MarketClock,
    OptionContract,
    OptionContractQuery,
    Page,
    PaperOrderIntent,
)
from app.domain.market_intelligence import MarketScanResult
from app.domain.reasoning import (
    MarketBias,
    MoneynessPreference,
    ProviderReasoningResult,
    TradeDecision,
    TradeRecommendation,
)
from app.infrastructure.database.models import AIDecisionRecord, TradeCandidateRecord
from app.infrastructure.database.session import Database
from app.infrastructure.repositories.trading import TradingRepository
from app.services.events import EventHub
from app.services.orchestrator import AgentOrchestrator
from tests.unit.test_reasoning_service import candidate


class FakeScanner:
    async def scan(self) -> MarketScanResult:
        item = candidate()
        return MarketScanResult(
            timestamp=item.timestamp,
            watchlist=(item.symbol,),
            opportunities=(item,),
        )


class NoTradeProvider:
    async def evaluate(self, candidate_json: str) -> ProviderReasoningResult:
        assert '"symbol":"SPY"' in candidate_json
        return ProviderReasoningResult(
            recommendation=TradeRecommendation(
                symbol="SPY",
                decision=TradeDecision.NO_TRADE,
                confidence=Decimal("0.8"),
                market_bias=MarketBias.NEUTRAL,
                thesis="The deterministic setup is not strong enough for a paper option entry.",
                supporting_factors=("Momentum was detected by the scanner.",),
                risk_factors=("Confirmation is insufficient for entry.",),
                preferred_moneyness=MoneynessPreference.ATM,
                minimum_days_to_expiry=7,
                maximum_days_to_expiry=21,
            )
        )

    async def close(self) -> None:
        return None


class ReadOnlyBroker:
    def __init__(self) -> None:
        self.contract_calls = 0
        self.order_calls = 0

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            id=uuid4(),
            status="ACTIVE",
            currency="USD",
            cash=Decimal("100000"),
            equity=Decimal("100000"),
            buying_power=Decimal("100000"),
            options_buying_power=Decimal("100000"),
        )

    async def get_market_clock(self) -> MarketClock:
        now = datetime(2026, 9, 3, 16, tzinfo=UTC)
        return MarketClock(
            timestamp=now,
            is_open=True,
            next_open=now + timedelta(days=1),
            next_close=now + timedelta(hours=4),
        )

    async def get_positions(self) -> tuple:
        return ()

    async def get_option_contracts(self, query: OptionContractQuery) -> Page[OptionContract]:
        self.contract_calls += 1
        raise AssertionError("NO_TRADE must not reach contract discovery")

    async def submit_order(self, intent: PaperOrderIntent) -> BrokerOrder:
        self.order_calls += 1
        raise AssertionError("NO_TRADE must not reach order submission")


async def test_agent_persists_ai_rejection_without_reaching_execution(
    database: Database,
) -> None:
    settings = Settings(
        app_environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        alpaca_api_key=None,
        alpaca_secret_key=None,
        openai_api_key=None,
        order_submission_enabled=False,
        agent_autonomy_enabled=False,
    )
    broker = ReadOnlyBroker()
    agent = AgentOrchestrator(
        settings,
        database.session_factory,
        broker,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        NoTradeProvider(),
        FakeScanner(),  # type: ignore[arg-type]
        EventHub(),
    )

    status = await agent.run_once()

    assert status.cycle_state is AgentCycleState.IDLE
    assert status.last_error is None
    assert status.last_heartbeat is not None
    assert broker.contract_calls == 0
    assert broker.order_calls == 0
    async with database.session_factory() as session:
        candidate_record = (await session.execute(select(TradeCandidateRecord))).scalar_one()
        ai_record = (await session.execute(select(AIDecisionRecord))).scalar_one()
        assert candidate_record.status == "AI_REJECTED"
        assert ai_record.candidate_id == candidate_record.id
        assert ai_record.recommendation["decision"] == "NO_TRADE"


async def test_autonomy_switch_blocks_scheduler_start(database: Database) -> None:
    settings = Settings(
        app_environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        agent_autonomy_enabled=False,
    )
    agent = AgentOrchestrator(
        settings,
        database.session_factory,
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        EventHub(),
    )

    status = await agent.start()

    assert status.effective_state == "STOPPED"
    assert status.last_error == "Set AGENT_AUTONOMY_ENABLED=true to start scheduled cycles"


async def test_recovery_restores_persisted_kill_switch(database: Database) -> None:
    settings = Settings(
        app_environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        alpaca_api_key=None,
        alpaca_secret_key=None,
    )
    async with database.session_factory() as session:
        await TradingRepository(session).save_control(
            desired_state="KILLED",
            kill_switch_active=True,
            reason="persist across restart",
        )
    agent = AgentOrchestrator(
        settings,
        database.session_factory,
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        EventHub(),
    )

    status = await agent.recover()

    assert status.kill_switch_active is True
    assert status.effective_state == "KILLED"


async def test_unavailable_database_lock_prevents_scan(database: Database, monkeypatch) -> None:
    settings = Settings(
        app_environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    scanner = FakeScanner()
    agent = AgentOrchestrator(
        settings,
        database.session_factory,
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        scanner,  # type: ignore[arg-type]
        EventHub(),
    )
    called = False

    async def scan() -> MarketScanResult:
        nonlocal called
        called = True
        return await scanner.scan()

    @asynccontextmanager
    async def unavailable_lock(lock_id: int):
        yield False

    monkeypatch.setattr(scanner, "scan", scan)
    monkeypatch.setattr(agent, "_database_lock", unavailable_lock)

    status = await agent.run_once()

    assert called is False
    assert status.last_error == "ANOTHER_AGENT_INSTANCE_IS_ACTIVE"


async def test_unmanaged_broker_option_blocks_new_scan(database: Database, monkeypatch) -> None:
    settings = Settings(
        app_environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    broker = ReadOnlyBroker()
    scanner = FakeScanner()
    called = False

    async def positions() -> tuple[BrokerPosition, ...]:
        return (
            BrokerPosition(
                asset_id=uuid4(),
                symbol="SPY260925C00100000",
                asset_class="us_option",
                qty=Decimal("1"),
                side="long",
                avg_entry_price=Decimal("5"),
                cost_basis=Decimal("500"),
            ),
        )

    async def scan() -> MarketScanResult:
        nonlocal called
        called = True
        return await FakeScanner().scan()

    monkeypatch.setattr(broker, "get_positions", positions)
    monkeypatch.setattr(scanner, "scan", scan)
    agent = AgentOrchestrator(
        settings,
        database.session_factory,
        broker,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        scanner,  # type: ignore[arg-type]
        EventHub(),
    )

    status = await agent.run_once()

    assert called is False
    assert status.last_error == "POSITION_RECONCILIATION_REQUIRED"
