from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import DatabaseDependency, SettingsDependency

router = APIRouter()


class LiveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str
    version: str
    paper_trading: Literal[True] = True


class ReadyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready"] = "ready"
    database: Literal["connected"] = "connected"
    paper_trading: Literal[True] = True
    credentials_configured: bool
    llm_configured: bool
    order_submission_enabled: bool


@router.get("/live", response_model=LiveResponse)
async def live(settings: SettingsDependency) -> LiveResponse:
    return LiveResponse(service=settings.app_name, version=settings.app_version)


@router.get("/ready", response_model=ReadyResponse)
async def ready(settings: SettingsDependency, database: DatabaseDependency) -> ReadyResponse:
    await database.ping()
    return ReadyResponse(
        credentials_configured=settings.alpaca_credentials_configured,
        llm_configured=settings.openai_configured,
        order_submission_enabled=settings.order_submission_enabled,
    )
