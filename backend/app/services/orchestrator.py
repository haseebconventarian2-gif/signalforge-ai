from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import (
    BrokerError,
    ConflictError,
    PositionReconciliationRequiredError,
    SignalForgeError,
)
from app.domain.agent import AgentCycleState, AgentRuntimeStatus
from app.domain.broker import (
    AccountSnapshot,
    BrokerClient,
    BrokerPosition,
    MarketClock,
    MarketDataProvider,
    OptionContract,
    OptionContractQuery,
    OptionSnapshot,
    OptionType,
)
from app.domain.market_intelligence import CandidateOpportunity
from app.domain.monitoring import ExitPolicy
from app.domain.reasoning import LLMReasoningProvider, TradeDecision, TradeRecommendation
from app.domain.risk import RiskContext, RiskLimits, RiskStage, RiskVerdict
from app.infrastructure.repositories.ai_decisions import AIDecisionRepository
from app.infrastructure.repositories.trading import TradingRepository
from app.services.events import EventHub
from app.services.execution import ExecutionService
from app.services.monitoring import ExitEngine, PositionMonitor
from app.services.option_selector import OptionContractSelector
from app.services.reasoning import ReasoningService
from app.services.reconciliation import OrderReconciliationService
from app.services.risk_engine import RiskEngine
from app.services.scanner import MarketScanner

logger = structlog.get_logger(__name__)
ENTRY_LOCK_ID = 7_284_001_001
MONITOR_LOCK_ID = 7_284_001_002


def risk_limits_from_settings(settings: Settings) -> RiskLimits:
    return RiskLimits(
        max_risk_per_trade_pct=settings.risk_max_risk_per_trade_pct,
        max_premium_per_trade=settings.risk_max_premium_per_trade,
        max_portfolio_exposure_pct=settings.risk_max_portfolio_exposure_pct,
        max_open_positions=settings.risk_max_open_positions,
        max_underlying_exposure_pct=settings.risk_max_underlying_exposure_pct,
        min_ai_confidence=settings.risk_min_ai_confidence,
        max_daily_loss_pct=settings.risk_max_daily_loss_pct,
        max_consecutive_losses=settings.risk_max_consecutive_losses,
        cooldown_minutes=settings.risk_cooldown_minutes,
        max_quote_age_seconds=settings.risk_max_quote_age_seconds,
        min_volume_ratio=settings.risk_min_volume_ratio,
        max_bid_ask_spread_pct=settings.risk_max_bid_ask_spread_pct,
        min_dte=settings.risk_min_dte,
        max_dte=settings.risk_max_dte,
    )


class AgentOrchestrator:
    """Explicit, lock-protected state machine for bounded autonomous cycles."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        broker: BrokerClient,
        market_data: MarketDataProvider,
        llm_provider: LLMReasoningProvider,
        scanner: MarketScanner,
        events: EventHub,
    ) -> None:
        self._settings = settings
        self._sessions = session_factory
        self._broker = broker
        self._market_data = market_data
        self._llm_provider = llm_provider
        self._scanner = scanner
        self._events = events
        self._cycle_lock = asyncio.Lock()
        self._symbol_locks: dict[str, asyncio.Lock] = {}
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._desired_state = "STOPPED"
        self._effective_state = "STOPPED"
        self._cycle_state = AgentCycleState.IDLE
        self._kill_switch = settings.risk_kill_switch
        self._heartbeat: datetime | None = None
        self._last_error: str | None = None

    def status(self) -> AgentRuntimeStatus:
        return AgentRuntimeStatus(
            desired_state=self._desired_state,
            effective_state=self._effective_state,
            cycle_state=self._cycle_state,
            execution_enabled=self._settings.order_submission_enabled,
            autonomy_enabled=self._settings.agent_autonomy_enabled,
            kill_switch_active=self._kill_switch,
            running_cycle=self._cycle_lock.locked(),
            last_heartbeat=self._heartbeat,
            last_error=self._last_error,
        )

    async def start(self) -> AgentRuntimeStatus:
        await self._refresh_control()
        if not self._settings.agent_autonomy_enabled:
            self._last_error = "Set AGENT_AUTONOMY_ENABLED=true to start scheduled cycles"
            return self.status()
        if self._kill_switch:
            self._last_error = "Kill switch must be reset before starting"
            return self.status()
        self._desired_state = "RUNNING"
        self._effective_state = "RUNNING"
        self._stop.clear()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop(), name="signalforge-agent")
        await self._persist_control("Agent start requested")
        await self._publish("agent.status", self.status().model_dump(mode="json"))
        return self.status()

    async def pause(self) -> AgentRuntimeStatus:
        self._desired_state = "PAUSED"
        self._effective_state = "PAUSED"
        await self._persist_control("Agent pause requested")
        await self._publish("agent.status", self.status().model_dump(mode="json"))
        return self.status()

    async def activate_kill_switch(self) -> AgentRuntimeStatus:
        self._kill_switch = True
        self._desired_state = "KILLED"
        self._effective_state = "KILLED"
        await self._persist_control("Emergency kill switch activated")
        await self._monitor_positions(kill_switch=True)
        await self._publish("agent.status", self.status().model_dump(mode="json"))
        return self.status()

    async def reset_kill_switch(self) -> AgentRuntimeStatus:
        if self._settings.risk_kill_switch:
            raise ConflictError("The configuration kill switch cannot be reset through the API")
        self._kill_switch = False
        self._desired_state = "STOPPED"
        self._effective_state = "STOPPED"
        self._last_error = None
        await self._persist_control("Kill switch reset")
        await self._publish("agent.status", self.status().model_dump(mode="json"))
        return self.status()

    async def shutdown(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
        self._effective_state = "STOPPED"

    async def recover(self) -> AgentRuntimeStatus:
        """Restore durable safety state and reconcile persisted orders without submitting."""
        await self._refresh_control()
        if not self._settings.alpaca_credentials_configured:
            return self.status()
        try:
            await self._reconcile_orders()
            if not await self._position_inventory_consistent():
                self._last_error = "BROKER_POSITION_RECONCILIATION_REQUIRED"
        except BrokerError as exc:
            self._last_error = exc.code
            await logger.awarning("startup_reconciliation_deferred", error_code=exc.code)
        return self.status()

    async def run_once(self) -> AgentRuntimeStatus:
        if self._cycle_lock.locked():
            return self.status()
        async with self._cycle_lock:
            await self._refresh_control()
            if self._kill_switch:
                return self.status()
            async with self._database_lock(ENTRY_LOCK_ID) as acquired:
                if not acquired:
                    self._last_error = "ANOTHER_AGENT_INSTANCE_IS_ACTIVE"
                    return self.status()
                try:
                    await self._reconcile_orders()
                    broker_positions = await self._broker_option_positions()
                    if not await self._position_inventory_consistent(broker_positions):
                        raise PositionReconciliationRequiredError(
                            "Broker and database option positions require reconciliation"
                        )
                    await self._scan_cycle(broker_positions)
                    self._last_error = None
                except Exception as exc:
                    self._cycle_state = AgentCycleState.ERROR
                    self._last_error = (
                        exc.code if isinstance(exc, SignalForgeError) else type(exc).__name__
                    )
                    await logger.aexception("agent_cycle_failed")
                finally:
                    self._heartbeat = datetime.now(UTC)
                    self._cycle_state = AgentCycleState.IDLE
                    await self._publish("agent.status", self.status().model_dump(mode="json"))
        return self.status()

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            if self._desired_state == "RUNNING" and not self._kill_switch:
                await self.run_once()
            await self._monitor_positions(kill_switch=self._kill_switch)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._settings.agent_scan_interval_seconds
                )
            except TimeoutError:
                continue

    async def _scan_cycle(self, broker_positions: tuple[BrokerPosition, ...]) -> None:
        self._cycle_state = AgentCycleState.SCANNING
        scan = await self._scanner.scan()
        await self._publish("opportunities.scanned", scan.model_dump(mode="json"))
        if not scan.opportunities:
            return
        account = await self._broker.get_account()
        clock = await self._broker.get_market_clock()
        for candidate in scan.opportunities:
            lock = self._symbol_locks.setdefault(candidate.symbol, asyncio.Lock())
            if lock.locked():
                continue
            async with lock:
                await self._process_candidate(candidate, account, clock, broker_positions)

    async def _process_candidate(
        self,
        candidate: CandidateOpportunity,
        account: AccountSnapshot,
        clock: MarketClock,
        broker_positions: tuple[BrokerPosition, ...],
    ) -> None:
        async with self._sessions() as session:
            repository = TradingRepository(session)
            record = await repository.create_candidate(candidate)
            await repository.journal(
                "CANDIDATE_DISCOVERED",
                f"Deterministic opportunity discovered for {candidate.symbol}",
                correlation_id=record.correlation_id,
                candidate_id=record.id,
                details={"score": str(candidate.signal_score)},
            )
            self._cycle_state = AgentCycleState.AI_ANALYSIS
            reasoning = ReasoningService(
                self._llm_provider,
                AIDecisionRepository(session),
                model=self._settings.llm_model,
                maximum_input_characters=self._settings.openai_max_input_chars,
            )
            ai = await reasoning.evaluate(candidate, candidate_id=record.id)
            await self._publish("ai.decision", ai.model_dump(mode="json"))
            if ai.recommendation.decision is TradeDecision.NO_TRADE:
                await repository.update_candidate_status(record.id, "AI_REJECTED")
                return
            state = await repository.risk_state(candidate.symbol)
            option_exposure = sum(
                (self._position_exposure(position) for position in broker_positions), Decimal("0")
            )
            symbol_exposure = sum(
                (
                    self._position_exposure(position)
                    for position in broker_positions
                    if self._option_underlying(position.symbol) == candidate.symbol
                ),
                Decimal("0"),
            )
            state["total_exposure"] = option_exposure
            state["underlying_exposure"] = symbol_exposure
            state["open_position_count"] = len(broker_positions)
            state["duplicate_trade"] = await repository.has_active_underlying(
                candidate.symbol
            ) or any(
                self._option_underlying(position.symbol) == candidate.symbol
                for position in broker_positions
            )
            preliminary_context = self._risk_context(
                candidate, ai.recommendation, account, clock, state, RiskStage.PRELIMINARY
            )
            risk_engine = RiskEngine(risk_limits_from_settings(self._settings))
            self._cycle_state = AgentCycleState.RISK_EVALUATION
            preliminary = risk_engine.evaluate(preliminary_context)
            await repository.save_risk(record.id, preliminary)
            await self._publish("risk.decision", preliminary.model_dump(mode="json"))
            if preliminary.verdict is RiskVerdict.REJECTED:
                await repository.update_candidate_status(record.id, "RISK_REJECTED")
                return

            self._cycle_state = AgentCycleState.CONTRACT_SELECTION
            contracts = await self._contracts(candidate.symbol, ai.recommendation.decision)
            snapshots = await self._snapshots(tuple(item.symbol for item in contracts))
            selector = OptionContractSelector(
                min_dte=self._settings.risk_min_dte,
                max_dte=self._settings.risk_max_dte,
                target_dte=self._settings.option_target_dte,
                max_spread_pct=self._settings.risk_max_bid_ask_spread_pct,
                max_strike_distance_pct=self._settings.option_max_strike_distance_pct,
                min_bid_size=self._settings.option_min_bid_size,
                min_ask_size=self._settings.option_min_ask_size,
            )
            selection_result = selector.select(
                candidate,
                ai.recommendation,
                contracts,
                snapshots,
                as_of=clock.timestamp.date(),
                maximum_capital=preliminary.maximum_capital,
            )
            if selection_result.selected is None:
                await repository.update_candidate_status(record.id, "CONTRACT_REJECTED")
                return
            selection = selection_result.selected
            await repository.save_selection(record.id, selection)
            quote = selection.snapshot.latest_quote
            assert quote is not None
            final_context = preliminary_context.model_copy(
                update={
                    "stage": RiskStage.FINAL,
                    "quote_timestamp": quote.timestamp,
                    "bid": quote.bid_price,
                    "ask": quote.ask_price,
                    "bid_size": quote.bid_size,
                    "ask_size": quote.ask_size,
                    "dte": selection.days_to_expiry,
                    "contract_premium": selection.premium_per_contract,
                }
            )
            final_risk = risk_engine.evaluate(final_context)
            await repository.save_risk(
                record.id, final_risk, contract_symbol=selection.contract.symbol
            )
            await self._publish("risk.decision", final_risk.model_dump(mode="json"))
            if final_risk.verdict is RiskVerdict.REJECTED:
                await repository.update_candidate_status(record.id, "RISK_REJECTED")
                return
            self._cycle_state = AgentCycleState.READY_TO_EXECUTE
            if not self._settings.order_submission_enabled:
                await repository.update_candidate_status(record.id, "APPROVED")
                return
            execution = ExecutionService(
                self._broker,
                self._market_data,
                repository,
                maximum_quote_age_seconds=self._settings.risk_max_quote_age_seconds,
                stop_loss_pct=self._settings.exit_stop_loss_pct,
                take_profit_pct=self._settings.exit_take_profit_pct,
            )
            result = await execution.execute(record.id, candidate, final_risk, selection)
            await repository.update_candidate_status(record.id, result.status.value)
            await self._publish("order.updated", result.model_dump(mode="json"))

    def _risk_context(
        self,
        candidate: CandidateOpportunity,
        recommendation: TradeRecommendation,
        account: AccountSnapshot,
        clock: MarketClock,
        state: dict[str, Any],
        stage: RiskStage,
    ) -> RiskContext:
        last_loss = state["last_loss_at"]
        cooldown_until = (
            last_loss + timedelta(minutes=self._settings.risk_cooldown_minutes)
            if isinstance(last_loss, datetime)
            else None
        )
        return RiskContext(
            candidate=candidate,
            recommendation=recommendation,
            stage=stage,
            observed_at=clock.timestamp,
            equity=account.equity,
            options_buying_power=account.options_buying_power or account.buying_power,
            total_options_exposure=Decimal(str(state["total_exposure"])),
            underlying_exposure=Decimal(str(state["underlying_exposure"])),
            open_position_count=int(state["open_position_count"]),
            daily_realized_pnl=Decimal(str(state["daily_pnl"])),
            consecutive_losses=int(state["consecutive_losses"]),
            cooldown_until=cooldown_until,
            duplicate_trade=bool(state.get("duplicate_trade")),
            market_open=clock.is_open,
            kill_switch_active=self._kill_switch,
        )

    async def _contracts(self, symbol: str, decision: TradeDecision) -> tuple[OptionContract, ...]:
        option_type = OptionType.CALL if decision is TradeDecision.BUY_CALL else OptionType.PUT
        now = datetime.now(UTC).date()
        query = OptionContractQuery(
            underlying_symbols=(symbol,),
            expiration_date_gte=now + timedelta(days=self._settings.risk_min_dte),
            expiration_date_lte=now + timedelta(days=self._settings.risk_max_dte),
            option_type=option_type,
            limit=1000,
        )
        items: list[OptionContract] = []
        for _ in range(10):
            page = await self._broker.get_option_contracts(query)
            items.extend(page.items)
            if not page.next_page_token:
                break
            query = query.model_copy(update={"page_token": page.next_page_token})
        return tuple(items)

    async def _snapshots(self, symbols: tuple[str, ...]) -> tuple[OptionSnapshot, ...]:
        items: list[OptionSnapshot] = []
        for start in range(0, len(symbols), 100):
            items.extend(await self._market_data.get_option_snapshots(symbols[start : start + 100]))
        return tuple(items)

    async def _monitor_positions(self, *, kill_switch: bool) -> None:
        async with self._database_lock(MONITOR_LOCK_ID) as acquired:
            if not acquired:
                return
            async with self._sessions() as session:
                monitor = PositionMonitor(
                    self._broker,
                    self._market_data,
                    TradingRepository(session),
                    ExitEngine(
                        ExitPolicy(
                            stop_loss_pct=self._settings.exit_stop_loss_pct,
                            take_profit_pct=self._settings.exit_take_profit_pct,
                            maximum_holding_days=self._settings.exit_max_holding_days,
                            exit_dte=self._settings.exit_dte,
                        )
                    ),
                )
                results = await monitor.run_once(kill_switch_active=kill_switch)
                for result in results:
                    await self._publish("position.updated", result.model_dump(mode="json"))

    async def _reconcile_orders(self) -> None:
        async with self._sessions() as session:
            await OrderReconciliationService(
                self._broker,
                TradingRepository(session),
                stop_loss_pct=self._settings.exit_stop_loss_pct,
                take_profit_pct=self._settings.exit_take_profit_pct,
            ).run_once()

    async def _broker_option_positions(self) -> tuple[BrokerPosition, ...]:
        return tuple(
            position
            for position in await self._broker.get_positions()
            if position.asset_class == "us_option"
        )

    async def _position_inventory_consistent(
        self, broker_positions: tuple[BrokerPosition, ...] | None = None
    ) -> bool:
        broker_items = (
            broker_positions
            if broker_positions is not None
            else await self._broker_option_positions()
        )
        async with self._sessions() as session:
            local_items = await TradingRepository(session).list_open_positions()
        if any(
            item.side != "long" or item.qty != item.qty.to_integral_value()
            for item in broker_items
        ):
            return False
        broker_quantities = {item.symbol: int(item.qty) for item in broker_items}
        local_quantities = {item.contract_symbol: item.quantity for item in local_items}
        return broker_quantities == local_quantities

    @staticmethod
    def _option_underlying(contract_symbol: str) -> str:
        match = re.fullmatch(r"([A-Z]{1,6})\d{6}[CP]\d{8}", contract_symbol)
        return match.group(1) if match else contract_symbol

    @staticmethod
    def _position_exposure(position: BrokerPosition) -> Decimal:
        if position.cost_basis is not None:
            return abs(position.cost_basis)
        return abs(position.avg_entry_price * position.qty * 100)

    async def _refresh_control(self) -> None:
        async with self._sessions() as session:
            control = await TradingRepository(session).get_control()
        self._kill_switch = self._settings.risk_kill_switch or bool(
            control and control.kill_switch_active
        )
        if self._kill_switch:
            self._desired_state = "KILLED"
            self._effective_state = "KILLED"

    @asynccontextmanager
    async def _database_lock(self, lock_id: int) -> AsyncIterator[bool]:
        async with self._sessions() as session:
            bind = session.get_bind()
            if bind.dialect.name != "postgresql":
                yield True
                return
            acquired = bool(
                await session.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id}
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    await session.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id}
                    )

    async def _publish(self, event_type: str, data: dict[str, Any]) -> None:
        await self._events.publish(
            {"type": event_type, "timestamp": datetime.now(UTC).isoformat(), "data": data}
        )

    async def _persist_control(self, reason: str) -> None:
        async with self._sessions() as session:
            await TradingRepository(session).save_control(
                desired_state=self._desired_state,
                kill_switch_active=self._kill_switch,
                reason=reason,
            )
