from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import signalforge_error_handler, unexpected_error_handler
from app.api.middleware import RequestContextMiddleware
from app.api.router import api_router
from app.core.config import Environment, Settings, get_settings
from app.core.exceptions import SignalForgeError
from app.core.logging import configure_logging
from app.infrastructure.alpaca import AlpacaMarketDataClient, AlpacaPaperBroker
from app.infrastructure.alpaca.cli import AlpacaCliVerifier
from app.infrastructure.database.session import Database
from app.infrastructure.openai import OpenAIResponsesReasoningProvider
from app.services.events import EventHub
from app.services.indicators import IndicatorEngine
from app.services.market_data import MarketDataService
from app.services.opportunity import OpportunityDetector
from app.services.orchestrator import AgentOrchestrator
from app.services.scanner import MarketScanner


def create_app(settings: Settings | None = None) -> FastAPI:
    application_settings = settings or get_settings()
    configure_logging(application_settings.log_level)
    logger = structlog.get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(
            application_settings.database_url,
            echo=application_settings.database_echo,
            pool_size=application_settings.database_pool_size,
            max_overflow=application_settings.database_max_overflow,
            pool_timeout_seconds=application_settings.database_pool_timeout_seconds,
            transaction_pooler=application_settings.database_transaction_pooler,
        )
        app.state.settings = application_settings
        app.state.database = database
        app.state.broker = AlpacaPaperBroker(application_settings)
        app.state.market_data = AlpacaMarketDataClient(application_settings)
        app.state.llm_provider = OpenAIResponsesReasoningProvider(application_settings)
        app.state.events = EventHub()
        app.state.alpaca_cli = AlpacaCliVerifier(application_settings)
        app.state.market_scanner = MarketScanner(
            MarketDataService(
                app.state.market_data,
                lookback_days=application_settings.market_scan_lookback_days,
            ),
            IndicatorEngine(),
            OpportunityDetector(
                signal_threshold=application_settings.opportunity_signal_threshold,
                minimum_volume_ratio=application_settings.opportunity_min_volume_ratio,
                maximum_data_age_seconds=application_settings.market_max_data_age_seconds,
            ),
            watchlist=application_settings.watchlist_symbols,
        )
        app.state.agent = AgentOrchestrator(
            application_settings,
            database.session_factory,
            app.state.broker,
            app.state.market_data,
            app.state.llm_provider,
            app.state.market_scanner,
            app.state.events,
        )
        try:
            await database.ping()
            if application_settings.app_environment is not Environment.TEST:
                await app.state.agent.recover()
            await logger.ainfo(
                "application_started",
                **application_settings.public_summary(),
            )
            yield
        finally:
            await app.state.agent.shutdown()
            await app.state.broker.close()
            await app.state.market_data.close()
            await app.state.llm_provider.close()
            await database.dispose()
            await logger.ainfo("application_stopped")

    app = FastAPI(
        title=application_settings.app_name,
        version=application_settings.app_version,
        docs_url=f"{application_settings.api_v1_prefix}/docs",
        openapi_url=f"{application_settings.api_v1_prefix}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(application_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Control-Token"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(SignalForgeError, signalforge_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unexpected_error_handler)
    app.include_router(api_router, prefix=application_settings.api_v1_prefix)
    return app
