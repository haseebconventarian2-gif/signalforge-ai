from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from app.core.config import PAPER_TRADING_ORIGIN, Settings
from app.core.exceptions import (
    BrokerValidationError,
    OrderSubmissionDisabledError,
    PaperTradingViolation,
)
from app.domain.broker import (
    AccountSnapshot,
    BrokerOrder,
    BrokerPosition,
    MarketClock,
    OptionContract,
    OptionContractQuery,
    OrderSide,
    OrderType,
    Page,
    PaperOrderIntent,
    PositionIntent,
    ProviderAcknowledgement,
)
from app.infrastructure.alpaca.transport import AlpacaHttpTransport, AlpacaResponse


class AlpacaPaperBroker:
    """Paper-only implementation of the broker boundary."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings.alpaca_trading_base_url.rstrip("/").lower() != PAPER_TRADING_ORIGIN:
            raise PaperTradingViolation("Broker refused a non-paper Alpaca endpoint")
        self._settings = settings
        self._http = AlpacaHttpTransport(
            settings,
            base_url=PAPER_TRADING_ORIGIN,
            transport=transport,
        )

    async def get_account(self) -> AccountSnapshot:
        response = await self._http.request("GET", "/v2/account", safe_to_retry=True)
        payload = self._mapping(response)
        return AccountSnapshot.model_validate(
            {**payload, "provider_request_id": response.request_id}
        )

    async def get_market_clock(self) -> MarketClock:
        response = await self._http.request("GET", "/v2/clock", safe_to_retry=True)
        payload = self._mapping(response)
        return MarketClock.model_validate({**payload, "provider_request_id": response.request_id})

    async def get_positions(self) -> tuple[BrokerPosition, ...]:
        response = await self._http.request("GET", "/v2/positions", safe_to_retry=True)
        return tuple(
            BrokerPosition.model_validate({**item, "provider_request_id": response.request_id})
            for item in self._list(response)
        )

    async def get_open_orders(self) -> tuple[BrokerOrder, ...]:
        response = await self._http.request(
            "GET",
            "/v2/orders",
            params={"status": "open", "direction": "desc", "nested": False, "limit": 500},
            safe_to_retry=True,
        )
        return tuple(
            BrokerOrder.model_validate({**item, "provider_request_id": response.request_id})
            for item in self._list(response)
        )

    async def get_order(self, order_id: UUID) -> BrokerOrder:
        response = await self._http.request("GET", f"/v2/orders/{order_id}", safe_to_retry=True)
        payload = self._mapping(response)
        return BrokerOrder.model_validate({**payload, "provider_request_id": response.request_id})

    async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder:
        response = await self._http.request(
            "GET",
            "/v2/orders:by_client_order_id",
            params={"client_order_id": client_order_id},
            safe_to_retry=True,
        )
        payload = self._mapping(response)
        return BrokerOrder.model_validate({**payload, "provider_request_id": response.request_id})

    async def get_option_contracts(self, query: OptionContractQuery) -> Page[OptionContract]:
        params: dict[str, str | int | bool] = {
            "underlying_symbols": ",".join(query.underlying_symbols),
            "status": query.status,
            "limit": query.limit,
        }
        optional_values: dict[str, Any] = {
            "expiration_date": query.expiration_date,
            "expiration_date_gte": query.expiration_date_gte,
            "expiration_date_lte": query.expiration_date_lte,
            "type": query.option_type.value if query.option_type else None,
            "strike_price_gte": query.strike_price_gte,
            "strike_price_lte": query.strike_price_lte,
            "page_token": query.page_token,
        }
        params.update(
            {
                key: value.isoformat() if hasattr(value, "isoformat") else str(value)
                for key, value in optional_values.items()
                if value is not None
            }
        )
        response = await self._http.request(
            "GET", "/v2/options/contracts", params=params, safe_to_retry=True
        )
        payload = self._mapping(response)
        contracts = tuple(
            OptionContract.model_validate({**item, "provider_request_id": response.request_id})
            for item in payload.get("option_contracts", [])
        )
        return Page[OptionContract](
            items=contracts,
            next_page_token=payload.get("next_page_token"),
            provider_request_id=response.request_id,
        )

    async def submit_order(self, intent: PaperOrderIntent) -> BrokerOrder:
        if not self._settings.order_submission_enabled:
            raise OrderSubmissionDisabledError(
                "Set ORDER_SUBMISSION_ENABLED=true to permit guarded paper orders"
            )
        if intent.position_intent is PositionIntent.SELL_TO_CLOSE:
            await self._validate_owned_option_close(intent.symbol, intent.quantity)
        payload: dict[str, Any] = {
            "symbol": intent.symbol,
            "qty": str(intent.quantity),
            "side": intent.side.value,
            "type": intent.order_type.value,
            "time_in_force": "day",
            "position_intent": intent.position_intent.value,
            "client_order_id": intent.client_order_id,
            "order_class": "simple",
        }
        if intent.limit_price is not None:
            payload["limit_price"] = str(intent.limit_price)
        response = await self._http.request(
            "POST",
            "/v2/orders",
            json_body=payload,
            ambiguous_on_transport_error=True,
        )
        body = self._mapping(response)
        return BrokerOrder.model_validate({**body, "provider_request_id": response.request_id})

    async def cancel_order(self, order_id: UUID) -> ProviderAcknowledgement:
        if not self._settings.order_submission_enabled:
            raise OrderSubmissionDisabledError("Paper order cancellation is disabled")
        response = await self._http.request("DELETE", f"/v2/orders/{order_id}")
        return ProviderAcknowledgement(accepted=True, provider_request_id=response.request_id)

    async def close_owned_option_position(
        self,
        symbol: str,
        quantity: int,
        *,
        client_order_id: str,
        limit_price: Decimal,
    ) -> BrokerOrder:
        if not self._settings.order_submission_enabled:
            raise OrderSubmissionDisabledError("Paper position closing is disabled")
        if quantity <= 0:
            raise BrokerValidationError("Close quantity must be a positive integer")
        return await self.submit_order(
            PaperOrderIntent(
                symbol=symbol,
                quantity=quantity,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                position_intent=PositionIntent.SELL_TO_CLOSE,
                client_order_id=client_order_id,
                limit_price=limit_price,
            )
        )

    async def _validate_owned_option_close(self, symbol: str, quantity: int) -> None:
        positions = await self.get_positions()
        position = next((item for item in positions if item.symbol == symbol), None)
        if position is None:
            raise BrokerValidationError("Cannot close a position that is not currently owned")
        if position.asset_class != "us_option" or position.side != "long":
            raise BrokerValidationError("Only owned long option positions can be closed")
        if position.qty != position.qty.to_integral_value() or Decimal(quantity) > position.qty:
            raise BrokerValidationError("Close quantity exceeds the owned option quantity")

    @staticmethod
    def _mapping(response: AlpacaResponse) -> dict[str, Any]:
        if not isinstance(response.payload, dict):
            raise BrokerValidationError(
                "Alpaca returned an unexpected response object",
                context={"provider_request_id": response.request_id},
            )
        return response.payload

    @staticmethod
    def _list(response: AlpacaResponse) -> list[dict[str, Any]]:
        if not isinstance(response.payload, list) or not all(
            isinstance(item, dict) for item in response.payload
        ):
            raise BrokerValidationError(
                "Alpaca returned an unexpected response list",
                context={"provider_request_id": response.request_id},
            )
        return response.payload

    async def close(self) -> None:
        await self._http.close()
