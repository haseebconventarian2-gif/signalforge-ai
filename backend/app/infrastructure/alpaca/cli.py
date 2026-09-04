from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.config import PAPER_TRADING_ORIGIN, Settings


class AlpacaCliStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    installed: bool
    configured: bool
    connected: bool
    paper_verified: bool
    account_status: str | None = None
    message: str


class AlpacaCliVerifier:
    """Fixed read-only CLI verification with no execution command surface."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def verify(self) -> AlpacaCliStatus:
        executable = shutil.which(self._settings.alpaca_cli_executable)
        if executable is None:
            return AlpacaCliStatus(
                installed=False,
                configured=self._settings.alpaca_credentials_configured,
                connected=False,
                paper_verified=False,
                message="Official Alpaca CLI is not installed",
            )
        if not self._settings.alpaca_credentials_configured:
            return AlpacaCliStatus(
                installed=True,
                configured=False,
                connected=False,
                paper_verified=False,
                message="Alpaca paper credentials are not configured",
            )
        assert self._settings.alpaca_api_key is not None
        assert self._settings.alpaca_secret_key is not None
        environment = os.environ.copy()
        environment.update(
            {
                "APCA_API_BASE_URL": PAPER_TRADING_ORIGIN,
                "APCA_API_KEY_ID": self._settings.alpaca_api_key.get_secret_value(),
                "APCA_API_SECRET_KEY": self._settings.alpaca_secret_key.get_secret_value(),
            }
        )
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                "account",
                "get",
                "--quiet",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=self._settings.alpaca_cli_timeout_seconds
            )
        except TimeoutError:
            return AlpacaCliStatus(
                installed=True,
                configured=True,
                connected=False,
                paper_verified=True,
                message="Alpaca CLI read timed out",
            )
        if process.returncode != 0:
            return AlpacaCliStatus(
                installed=True,
                configured=True,
                connected=False,
                paper_verified=True,
                message="Alpaca CLI account read failed",
            )
        account_status = self._account_status(stdout)
        return AlpacaCliStatus(
            installed=True,
            configured=True,
            connected=True,
            paper_verified=True,
            account_status=account_status,
            message="Read-only Alpaca CLI paper account check passed",
        )

    @staticmethod
    def _account_status(payload: bytes) -> str | None:
        try:
            data: Any = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if isinstance(data, dict) and data.get("status") is not None:
            return str(data["status"])
        return None
