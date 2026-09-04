# Alpaca Paper Integration

## Scope

Phase 2 introduces provider-independent broker and market-data protocols plus raw HTTP adapters for Alpaca. It does not implement autonomous trading, strategy logic, position sizing, or a path around the future risk engine.

## Boundaries

- `BrokerClient` defines account, clock, positions, orders, option contracts, and guarded paper mutations.
- `MarketDataProvider` defines historical bars and current stock/option snapshots.
- `AlpacaPaperBroker` always uses `https://paper-api.alpaca.markets`.
- `AlpacaMarketDataClient` always uses `https://data.alpaca.markets`.
- Pydantic domain models normalize provider strings, timestamps, UUIDs, and financial `Decimal` values.

The implementation follows Alpaca's official [Trading API](https://docs.alpaca.markets/us/docs/getting-started-with-trading-api), [option contract](https://docs.alpaca.markets/us/reference/get-options-contracts), [option snapshot](https://docs.alpaca.markets/us/reference/optionsnapshots), and [option order](https://docs.alpaca.markets/us/docs/options-trading-overview) documentation.

## Retry and Failure Policy

- Account, clock, positions, orders, contracts, and market-data GET requests retry bounded network failures, HTTP `429`, and HTTP `5xx` responses.
- Backoff is exponential and honors a bounded numeric `Retry-After` value.
- Mutations are never automatically retried.
- A timeout or transport failure during order submission raises `AMBIGUOUS_ORDER_SUBMISSION`; callers must reconcile by `client_order_id` before any later attempt.
- Provider errors become typed application exceptions without logging response bodies or credentials.
- Alpaca's `X-Request-ID` is attached to normalized responses/errors and emitted in structured logs for later persistence with lifecycle records.

## Order Safety

- The adapter accepts only integer quantities.
- Options orders are constrained to `day` time in force and `simple` order class.
- The only accepted intents are `buy_to_open` and `sell_to_close`.
- Submission, cancellation, and closing require `ORDER_SUBMISSION_ENABLED=true`.
- Closing first verifies the account owns a long `us_option` position and rejects quantities above the owned amount.
- No generic arbitrary-payload or live-endpoint method is exposed.

## Read-Only Check

`GET /api/v1/integrations/alpaca/connectivity` reads account and market-clock state. It never submits or changes an order. Without credentials it returns a safe, unconfigured status.
