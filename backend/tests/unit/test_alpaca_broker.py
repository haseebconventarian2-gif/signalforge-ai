from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings
from app.core.exceptions import (
    AmbiguousOrderSubmissionError,
    BrokerAuthenticationError,
    BrokerRateLimitError,
    BrokerValidationError,
    OrderSubmissionDisabledError,
    PaperTradingViolation,
)
from app.domain.broker import (
    OptionContractQuery,
    OptionType,
    OrderSide,
    OrderType,
    PaperOrderIntent,
    PositionIntent,
)
from app.infrastructure.alpaca.broker import AlpacaPaperBroker

ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"
ASSET_ID = "22222222-2222-4222-8222-222222222222"
ORDER_ID = "33333333-3333-4333-8333-333333333333"
CONTRACT_ID = "44444444-4444-4444-8444-444444444444"
OPTION_SYMBOL = "AAPL261016C00200000"
NOW = "2026-09-03T15:00:00Z"


def settings(*, execution: bool = False, retries: int = 0) -> Settings:
    return Settings(
        app_environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        alpaca_api_key="paper-key",
        alpaca_secret_key="paper-secret",
        order_submission_enabled=execution,
        control_api_token="a" * 32 if execution else None,
        alpaca_max_safe_retries=retries,
        alpaca_retry_base_seconds=0,
    )


def response(request: httpx.Request, status: int, payload=None, request_id: str = "req-1"):
    return httpx.Response(
        status,
        json=payload,
        headers={"X-Request-ID": request_id},
        request=request,
    )


def account_payload() -> dict:
    return {
        "id": ACCOUNT_ID,
        "status": "ACTIVE",
        "currency": "USD",
        "cash": "90000",
        "equity": "100000",
        "buying_power": "180000",
        "options_buying_power": "75000",
        "options_approved_level": 2,
        "options_trading_level": 2,
    }


def order_payload() -> dict:
    return {
        "id": ORDER_ID,
        "client_order_id": "candidate-1",
        "status": "accepted",
        "symbol": OPTION_SYMBOL,
        "asset_class": "us_option",
        "qty": "1",
        "filled_qty": "0",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": "2.50",
        "position_intent": "buy_to_open",
        "created_at": NOW,
        "submitted_at": NOW,
    }


async def test_account_and_clock_are_normalized_with_request_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["APCA-API-KEY-ID"] == "paper-key"
        if request.url.path == "/v2/account":
            return response(request, 200, account_payload(), "account-request")
        return response(
            request,
            200,
            {"timestamp": NOW, "is_open": True, "next_open": NOW, "next_close": NOW},
            "clock-request",
        )

    broker = AlpacaPaperBroker(settings(), transport=httpx.MockTransport(handler))
    account = await broker.get_account()
    clock = await broker.get_market_clock()
    await broker.close()

    assert account.options_buying_power == 75000
    assert account.provider_request_id == "account-request"
    assert clock.is_open is True
    assert clock.provider_request_id == "clock-request"


async def test_option_contract_query_uses_documented_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["underlying_symbols"] == "AAPL"
        assert request.url.params["type"] == "call"
        assert request.url.params["expiration_date_gte"] == "2026-09-10"
        return response(
            request,
            200,
            {
                "option_contracts": [
                    {
                        "id": CONTRACT_ID,
                        "symbol": OPTION_SYMBOL,
                        "name": "AAPL Oct 16 2026 200 Call",
                        "status": "active",
                        "tradable": True,
                        "expiration_date": "2026-10-16",
                        "root_symbol": "AAPL",
                        "underlying_symbol": "AAPL",
                        "type": "call",
                        "style": "american",
                        "strike_price": "200",
                    }
                ],
                "next_page_token": "next",
            },
        )

    broker = AlpacaPaperBroker(settings(), transport=httpx.MockTransport(handler))
    result = await broker.get_option_contracts(
        OptionContractQuery(
            underlying_symbols=("AAPL",),
            option_type=OptionType.CALL,
            expiration_date_gte=datetime(2026, 9, 10, tzinfo=UTC).date(),
        )
    )
    await broker.close()

    assert result.items[0].symbol == OPTION_SYMBOL
    assert result.next_page_token == "next"


async def test_safe_read_retries_rate_limit_but_returns_bounded_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response(request, 429, {"message": "slow down"})

    broker = AlpacaPaperBroker(settings(retries=2), transport=httpx.MockTransport(handler))
    with pytest.raises(BrokerRateLimitError):
        await broker.get_account()
    await broker.close()
    assert attempts == 3


async def test_authentication_failure_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response(request, 401, {"message": "unauthorized"})

    broker = AlpacaPaperBroker(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(BrokerAuthenticationError):
        await broker.get_account()
    await broker.close()


async def test_order_submission_is_disabled_by_default() -> None:
    broker = AlpacaPaperBroker(settings(), transport=httpx.MockTransport(lambda _: None))
    intent = PaperOrderIntent(
        symbol=OPTION_SYMBOL,
        quantity=1,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        position_intent=PositionIntent.BUY_TO_OPEN,
        client_order_id="candidate-1",
        limit_price="2.50",
    )
    with pytest.raises(OrderSubmissionDisabledError):
        await broker.submit_order(intent)
    await broker.close()


async def test_paper_order_payload_is_constrained_and_not_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        payload = __import__("json").loads(request.content)
        assert payload["position_intent"] == "buy_to_open"
        assert payload["time_in_force"] == "day"
        assert payload["order_class"] == "simple"
        return response(request, 200, order_payload(), "order-request")

    broker = AlpacaPaperBroker(
        settings(execution=True, retries=3), transport=httpx.MockTransport(handler)
    )
    order = await broker.submit_order(
        PaperOrderIntent(
            symbol=OPTION_SYMBOL,
            quantity=1,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            position_intent=PositionIntent.BUY_TO_OPEN,
            client_order_id="candidate-1",
            limit_price="2.50",
        )
    )
    await broker.close()

    assert order.id == UUID(ORDER_ID)
    assert order.provider_request_id == "order-request"
    assert attempts == 1


async def test_timed_out_order_is_ambiguous_and_never_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("unknown state", request=request)

    broker = AlpacaPaperBroker(
        settings(execution=True, retries=3), transport=httpx.MockTransport(handler)
    )
    intent = PaperOrderIntent(
        symbol=OPTION_SYMBOL,
        quantity=1,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        position_intent=PositionIntent.BUY_TO_OPEN,
        client_order_id="candidate-1",
    )
    with pytest.raises(AmbiguousOrderSubmissionError):
        await broker.submit_order(intent)
    await broker.close()
    assert attempts == 1


async def test_server_error_during_order_submission_is_ambiguous() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response(request, 503, {"message": "upstream unavailable"}, "request-503")

    broker = AlpacaPaperBroker(
        settings(execution=True, retries=3), transport=httpx.MockTransport(handler)
    )
    intent = PaperOrderIntent(
        symbol=OPTION_SYMBOL,
        quantity=1,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        position_intent=PositionIntent.BUY_TO_OPEN,
        client_order_id="candidate-1",
        limit_price="2.50",
    )

    with pytest.raises(AmbiguousOrderSubmissionError) as captured:
        await broker.submit_order(intent)
    await broker.close()

    assert captured.value.context["provider_request_id"] == "request-503"
    assert attempts == 1


async def test_open_orders_lookup_and_cancellation_are_supported() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "DELETE":
            return httpx.Response(
                204,
                headers={"X-Request-ID": "cancel-request"},
                request=request,
            )
        if request.url.path == "/v2/orders":
            assert request.url.params["status"] == "open"
            return response(request, 200, [order_payload()])
        return response(request, 200, order_payload())

    broker = AlpacaPaperBroker(settings(execution=True), transport=httpx.MockTransport(handler))
    open_orders = await broker.get_open_orders()
    order = await broker.get_order(UUID(ORDER_ID))
    acknowledgement = await broker.cancel_order(UUID(ORDER_ID))
    await broker.close()

    assert open_orders[0].id == UUID(ORDER_ID)
    assert order.client_order_id == "candidate-1"
    assert acknowledgement.accepted is True
    assert acknowledgement.provider_request_id == "cancel-request"
    assert calls[-1] == f"DELETE /v2/orders/{ORDER_ID}"


def test_order_intent_rejects_short_opening_and_invalid_limit_orders() -> None:
    with pytest.raises(ValidationError, match="buy-to-open and sell-to-close"):
        PaperOrderIntent(
            symbol=OPTION_SYMBOL,
            quantity=1,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            position_intent=PositionIntent.BUY_TO_OPEN,
            client_order_id="candidate-1",
        )
    with pytest.raises(ValidationError, match="require a positive limit price"):
        PaperOrderIntent(
            symbol=OPTION_SYMBOL,
            quantity=1,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            position_intent=PositionIntent.BUY_TO_OPEN,
            client_order_id="candidate-1",
        )


async def test_close_requires_owned_long_option_and_caps_quantity() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/v2/positions":
            return response(
                request,
                200,
                [
                    {
                        "asset_id": ASSET_ID,
                        "symbol": OPTION_SYMBOL,
                        "asset_class": "us_option",
                        "qty": "2",
                        "side": "long",
                        "avg_entry_price": "2.10",
                    }
                ],
            )
        payload = __import__("json").loads(request.content)
        assert payload["side"] == "sell"
        assert payload["position_intent"] == "sell_to_close"
        assert payload["client_order_id"] == "close-candidate-1"
        return response(request, 200, order_payload())

    broker = AlpacaPaperBroker(settings(execution=True), transport=httpx.MockTransport(handler))
    with pytest.raises(BrokerValidationError, match="exceeds"):
        await broker.close_owned_option_position(
            OPTION_SYMBOL,
            3,
            client_order_id="close-candidate-1",
            limit_price=Decimal("2.00"),
        )
    order = await broker.close_owned_option_position(
        OPTION_SYMBOL,
        1,
        client_order_id="close-candidate-1",
        limit_price=Decimal("2.00"),
    )
    await broker.close()

    assert order.symbol == OPTION_SYMBOL
    assert calls[-1] == "POST /v2/orders"


def test_broker_rechecks_paper_endpoint_at_its_boundary() -> None:
    unsafe = settings()
    unsafe.alpaca_trading_base_url = "https://example.invalid"
    with pytest.raises(PaperTradingViolation):
        AlpacaPaperBroker(unsafe)
