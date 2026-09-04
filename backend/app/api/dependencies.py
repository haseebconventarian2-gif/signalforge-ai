from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ControlAuthenticationError, ControlUnavailableError
from app.domain.broker import BrokerClient, MarketDataProvider
from app.domain.reasoning import LLMReasoningProvider
from app.infrastructure.alpaca.cli import AlpacaCliVerifier
from app.infrastructure.database.session import Database
from app.infrastructure.repositories.ai_decisions import AIDecisionRepository
from app.services.events import EventHub
from app.services.orchestrator import AgentOrchestrator
from app.services.reasoning import ReasoningService
from app.services.scanner import MarketScanner


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_broker(request: Request) -> BrokerClient:
    return cast(BrokerClient, request.app.state.broker)


def get_market_data(request: Request) -> MarketDataProvider:
    return cast(MarketDataProvider, request.app.state.market_data)


def get_market_scanner(request: Request) -> MarketScanner:
    return cast(MarketScanner, request.app.state.market_scanner)


def get_llm_provider(request: Request) -> LLMReasoningProvider:
    return cast(LLMReasoningProvider, request.app.state.llm_provider)


def get_agent(request: Request) -> AgentOrchestrator:
    return cast(AgentOrchestrator, request.app.state.agent)


def require_control_authorization(
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_control_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.control_api_token_value
    if expected is None:
        raise ControlUnavailableError("Set CONTROL_API_TOKEN to enable agent mutation endpoints")
    if x_control_token is None or not hmac.compare_digest(x_control_token, expected):
        raise ControlAuthenticationError("A valid X-Control-Token header is required")


def get_event_hub(request: Request) -> EventHub:
    return cast(EventHub, request.app.state.events)


def get_alpaca_cli(request: Request) -> AlpacaCliVerifier:
    return cast(AlpacaCliVerifier, request.app.state.alpaca_cli)


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_reasoning_service(
    settings: SettingsDependency,
    session: SessionDependency,
    provider: Annotated[LLMReasoningProvider, Depends(get_llm_provider)],
) -> ReasoningService:
    return ReasoningService(
        provider,
        AIDecisionRepository(session),
        model=settings.llm_model,
        maximum_input_characters=settings.openai_max_input_chars,
    )


SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
DatabaseDependency = Annotated[Database, Depends(get_database)]
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
BrokerDependency = Annotated[BrokerClient, Depends(get_broker)]
MarketDataDependency = Annotated[MarketDataProvider, Depends(get_market_data)]
MarketScannerDependency = Annotated[MarketScanner, Depends(get_market_scanner)]
ReasoningServiceDependency = Annotated[ReasoningService, Depends(get_reasoning_service)]
AgentDependency = Annotated[AgentOrchestrator, Depends(get_agent)]
EventHubDependency = Annotated[EventHub, Depends(get_event_hub)]
AlpacaCliDependency = Annotated[AlpacaCliVerifier, Depends(get_alpaca_cli)]
ControlAuthorizationDependency = Annotated[None, Depends(require_control_authorization)]
