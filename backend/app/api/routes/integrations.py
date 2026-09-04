from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import AlpacaCliDependency, BrokerDependency, SettingsDependency
from app.infrastructure.alpaca.cli import AlpacaCliStatus

router = APIRouter()


class AlpacaConnectivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    connected: bool
    paper_trading: Literal[True] = True
    account_status: str | None = None
    market_open: bool | None = None
    options_buying_power_available: bool | None = None
    provider_request_ids: tuple[str, ...] = ()
    message: str


@router.get("/alpaca/connectivity", response_model=AlpacaConnectivityResponse)
async def alpaca_connectivity(
    settings: SettingsDependency,
    broker: BrokerDependency,
) -> AlpacaConnectivityResponse:
    """Perform account and market-clock reads; this endpoint never submits an order."""
    if not settings.alpaca_credentials_configured:
        return AlpacaConnectivityResponse(
            configured=False,
            connected=False,
            message="Alpaca paper credentials are not configured",
        )
    account = await broker.get_account()
    clock = await broker.get_market_clock()
    request_ids = tuple(
        request_id
        for request_id in (account.provider_request_id, clock.provider_request_id)
        if request_id
    )
    return AlpacaConnectivityResponse(
        configured=True,
        connected=True,
        account_status=account.status,
        market_open=clock.is_open,
        options_buying_power_available=account.options_buying_power is not None,
        provider_request_ids=request_ids,
        message="Connected to Alpaca paper trading",
    )


@router.get("/alpaca-cli", response_model=AlpacaCliStatus)
async def alpaca_cli_connectivity(cli: AlpacaCliDependency) -> AlpacaCliStatus:
    """Run the fixed read-only official CLI account check."""
    return await cli.verify()
