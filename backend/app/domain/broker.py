from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class PositionIntent(StrEnum):
    BUY_TO_OPEN = "buy_to_open"
    SELL_TO_CLOSE = "sell_to_close"


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


class AccountSnapshot(DomainModel):
    id: UUID
    status: str
    currency: str
    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    options_buying_power: Decimal | None = None
    options_approved_level: int | None = None
    options_trading_level: int | None = None
    trading_blocked: bool = False
    account_blocked: bool = False
    pattern_day_trader: bool = False
    provider_request_id: str | None = None


class MarketClock(DomainModel):
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime
    provider_request_id: str | None = None


class BrokerPosition(DomainModel):
    asset_id: UUID
    symbol: str
    asset_class: str
    qty: Decimal
    side: Literal["long", "short"]
    avg_entry_price: Decimal
    market_value: Decimal | None = None
    cost_basis: Decimal | None = None
    unrealized_pl: Decimal | None = None
    unrealized_plpc: Decimal | None = None
    current_price: Decimal | None = None
    provider_request_id: str | None = None


class BrokerOrder(DomainModel):
    id: UUID
    client_order_id: str
    status: str
    symbol: str
    asset_class: str | None = None
    qty: Decimal | None = None
    filled_qty: Decimal = Decimal("0")
    filled_avg_price: Decimal | None = None
    side: OrderSide
    type: OrderType
    time_in_force: str
    limit_price: Decimal | None = None
    position_intent: str | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    canceled_at: datetime | None = None
    failed_at: datetime | None = None
    provider_request_id: str | None = None


class OptionContract(DomainModel):
    id: UUID
    symbol: str
    name: str
    status: str
    tradable: bool
    expiration_date: date
    root_symbol: str
    underlying_symbol: str
    type: OptionType
    style: str
    strike_price: Decimal
    provider_request_id: str | None = None


class Bar(DomainModel):
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int | None = None
    volume_weighted_price: Decimal | None = None


class Quote(DomainModel):
    timestamp: datetime
    bid_price: Decimal
    bid_size: Decimal
    ask_price: Decimal
    ask_size: Decimal


class Trade(DomainModel):
    timestamp: datetime
    price: Decimal
    size: Decimal


class StockSnapshot(DomainModel):
    symbol: str
    latest_trade: Trade | None = None
    latest_quote: Quote | None = None
    minute_bar: Bar | None = None
    daily_bar: Bar | None = None
    previous_daily_bar: Bar | None = None
    provider_request_id: str | None = None


class OptionGreeks(DomainModel):
    delta: Decimal | None = None
    gamma: Decimal | None = None
    theta: Decimal | None = None
    vega: Decimal | None = None
    rho: Decimal | None = None


class OptionSnapshot(DomainModel):
    symbol: str
    latest_trade: Trade | None = None
    latest_quote: Quote | None = None
    implied_volatility: Decimal | None = None
    greeks: OptionGreeks | None = None
    provider_request_id: str | None = None


class OptionContractQuery(DomainModel):
    underlying_symbols: tuple[str, ...]
    status: Literal["active", "inactive"] = "active"
    expiration_date: date | None = None
    expiration_date_gte: date | None = None
    expiration_date_lte: date | None = None
    option_type: OptionType | None = None
    strike_price_gte: Decimal | None = None
    strike_price_lte: Decimal | None = None
    limit: Annotated[int, Field(ge=1, le=10_000)] = 100
    page_token: str | None = None


class HistoricalBarsQuery(DomainModel):
    symbols: tuple[str, ...]
    timeframe: str
    start: datetime
    end: datetime | None = None
    limit: Annotated[int, Field(ge=1, le=10_000)] = 1_000
    page_token: str | None = None


class PaperOrderIntent(DomainModel):
    symbol: Annotated[str, Field(min_length=1, max_length=64)]
    quantity: Annotated[int, Field(gt=0)]
    side: OrderSide
    order_type: OrderType
    position_intent: PositionIntent
    client_order_id: Annotated[str, Field(min_length=1, max_length=48)]
    limit_price: Annotated[Decimal | None, Field(gt=0)] = None

    @model_validator(mode="after")
    def validate_supported_intent(self) -> PaperOrderIntent:
        valid_pair = (self.side, self.position_intent) in {
            (OrderSide.BUY, PositionIntent.BUY_TO_OPEN),
            (OrderSide.SELL, PositionIntent.SELL_TO_CLOSE),
        }
        if not valid_pair:
            raise ValueError("Only buy-to-open and sell-to-close intents are supported")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("Limit orders require a positive limit price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("Market orders cannot include a limit price")
        return self


class ProviderAcknowledgement(DomainModel):
    accepted: bool
    provider_request_id: str | None = None


class Page[T](DomainModel):
    items: tuple[T, ...]
    next_page_token: str | None = None
    provider_request_id: str | None = None


class BrokerClient(Protocol):
    async def get_account(self) -> AccountSnapshot: ...
    async def get_market_clock(self) -> MarketClock: ...
    async def get_positions(self) -> tuple[BrokerPosition, ...]: ...
    async def get_open_orders(self) -> tuple[BrokerOrder, ...]: ...
    async def get_order(self, order_id: UUID) -> BrokerOrder: ...
    async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder: ...
    async def get_option_contracts(self, query: OptionContractQuery) -> Page[OptionContract]: ...
    async def submit_order(self, intent: PaperOrderIntent) -> BrokerOrder: ...
    async def cancel_order(self, order_id: UUID) -> ProviderAcknowledgement: ...
    async def close_owned_option_position(
        self,
        symbol: str,
        quantity: int,
        *,
        client_order_id: str,
        limit_price: Decimal,
    ) -> BrokerOrder: ...
    async def close(self) -> None: ...


class MarketDataProvider(Protocol):
    async def get_historical_bars(self, query: HistoricalBarsQuery) -> Page[Bar]: ...
    async def get_stock_snapshots(self, symbols: tuple[str, ...]) -> tuple[StockSnapshot, ...]: ...
    async def get_option_snapshots(
        self, symbols: tuple[str, ...]
    ) -> tuple[OptionSnapshot, ...]: ...
    async def close(self) -> None: ...
