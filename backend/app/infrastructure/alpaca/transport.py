from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from app.core.config import Settings
from app.core.exceptions import (
    AmbiguousOrderSubmissionError,
    BrokerAuthenticationError,
    BrokerError,
    BrokerOrderRejectedError,
    BrokerPermissionError,
    BrokerRateLimitError,
    BrokerTimeoutError,
    BrokerValidationError,
    ConfigurationError,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AlpacaResponse:
    payload: Any
    request_id: str | None
    status_code: int


class AlpacaHttpTransport:
    """Authenticated HTTP transport with retries limited to safe reads."""

    def __init__(
        self,
        settings: Settings,
        *,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._authentication_headers(settings),
            timeout=httpx.Timeout(settings.alpaca_request_timeout_seconds),
            transport=transport,
        )

    @staticmethod
    def _authentication_headers(settings: Settings) -> dict[str, str]:
        if not settings.alpaca_credentials_configured:
            return {}
        assert settings.alpaca_api_key is not None
        assert settings.alpaca_secret_key is not None
        return {
            "APCA-API-KEY-ID": settings.alpaca_api_key.get_secret_value(),
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key.get_secret_value(),
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int | bool] | None = None,
        json_body: dict[str, Any] | None = None,
        safe_to_retry: bool = False,
        ambiguous_on_transport_error: bool = False,
    ) -> AlpacaResponse:
        if not self._settings.alpaca_credentials_configured:
            raise ConfigurationError("Alpaca paper credentials are not configured")

        attempts = self._settings.alpaca_max_safe_retries + 1 if safe_to_retry else 1
        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                )
            except httpx.TimeoutException as exc:
                if safe_to_retry and attempt + 1 < attempts:
                    await self._backoff(attempt)
                    continue
                timeout_error_type = (
                    AmbiguousOrderSubmissionError
                    if ambiguous_on_transport_error
                    else BrokerTimeoutError
                )
                raise timeout_error_type(
                    "Alpaca request timed out",
                    context={"method": method, "path": path},
                ) from exc
            except httpx.TransportError as exc:
                if safe_to_retry and attempt + 1 < attempts:
                    await self._backoff(attempt)
                    continue
                transport_error_type = (
                    AmbiguousOrderSubmissionError if ambiguous_on_transport_error else BrokerError
                )
                raise transport_error_type(
                    "Alpaca network request failed",
                    context={"method": method, "path": path},
                ) from exc

            request_id = response.headers.get("X-Request-ID")
            if safe_to_retry and response.status_code == 429 and attempt + 1 < attempts:
                await self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            if safe_to_retry and response.status_code >= 500 and attempt + 1 < attempts:
                await self._backoff(attempt)
                continue

            await logger.ainfo(
                "alpaca_response",
                method=method,
                path=path,
                status_code=response.status_code,
                provider_request_id=request_id,
                attempt=attempt + 1,
            )
            if response.is_error:
                if ambiguous_on_transport_error and response.status_code >= 500:
                    raise AmbiguousOrderSubmissionError(
                        "Alpaca order response did not prove whether submission succeeded",
                        context={
                            "method": method,
                            "path": path,
                            "status_code": response.status_code,
                            "provider_request_id": request_id,
                        },
                    )
                self._raise_response_error(response, request_id, method, path)
            payload: Any = None
            if response.content:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise BrokerValidationError(
                        "Alpaca returned malformed JSON",
                        context={"provider_request_id": request_id, "path": path},
                    ) from exc
            return AlpacaResponse(payload, request_id, response.status_code)

        raise BrokerError("Alpaca request exhausted its retry policy")

    async def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self._settings.alpaca_retry_base_seconds * (2**attempt)
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), 5.0))
            except ValueError:
                pass
        await asyncio.sleep(delay)

    @staticmethod
    def _raise_response_error(
        response: httpx.Response,
        request_id: str | None,
        method: str,
        path: str,
    ) -> None:
        try:
            body = response.json()
            message = str(body.get("message") or body.get("error") or "Alpaca request failed")
            provider_code = body.get("code")
        except ValueError:
            message = "Alpaca request failed"
            provider_code = None
        context = {
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "provider_code": provider_code,
            "provider_request_id": request_id,
        }
        if response.status_code == 401:
            raise BrokerAuthenticationError(message, context=context)
        if response.status_code == 403:
            error = BrokerOrderRejectedError if method == "POST" else BrokerPermissionError
            raise error(message, context=context)
        if response.status_code == 429:
            raise BrokerRateLimitError(message, context=context)
        if response.status_code in {400, 404, 422}:
            raise BrokerValidationError(message, context=context)
        raise BrokerError(message, context=context)

    async def close(self) -> None:
        await self._client.aclose()
