# Market Intelligence

Phase 3 adds deterministic, read-only market analysis. It does not call an LLM, discover
option contracts, assess portfolio risk, or submit orders.

## Data flow

1. `MarketScanner` starts one bounded scan of the configured watchlist.
2. `MarketDataService` retrieves ascending daily bars and current stock snapshots through the
   mockable `MarketDataProvider` protocol.
3. `IndicatorEngine` calculates one immutable `IndicatorSnapshot` for each symbol with at least
   60 valid bars.
4. `OpportunityDetector` combines independent trend and momentum evidence into a signed score.
5. Symbols that pass freshness, volume, and score gates become `CandidateOpportunity` objects.

The scanner isolates insufficient history for one symbol instead of failing the entire watchlist.
Provider failures still fail the scan explicitly rather than producing fabricated results.

## Indicator definitions

All calculations use `Decimal` and bars ordered by timestamp.

| Indicator | Definition |
| --- | --- |
| Period return | `close[t] / close[t-1] - 1` |
| SMA 20 | Arithmetic mean of the latest 20 closes |
| EMA 20/50 | Recursive EMA with `alpha = 2 / (period + 1)`, seeded by the first close |
| RSI 14 | Wilder-smoothed average gains/losses; flat input is 50 and zero losses is 100 |
| MACD | EMA 12 minus EMA 26; signal is a 9-period EMA of MACD |
| ATR 14 | Wilder-smoothed true range using gaps from the previous close |
| Volume ratio 20 | Latest volume divided by mean volume of the preceding 20 bars |
| Volatility 20 | Sample standard deviation of 20 log returns, annualized by `sqrt(252)` |
| Recent high/low | Maximum high and minimum low over the latest 20 bars |
| Momentum 10 | `close[t] / close[t-10] - 1` |
| Trend strength | Absolute EMA 20/50 distance divided by ATR 14 |

## Opportunity score

Each component is clamped to `[-1, 1]`. Positive values are bullish and negative values are
bearish.

```text
trend   = clamp((EMA20 - EMA50) / ATR14)
macd    = clamp(MACD histogram / ATR14)
momentum= clamp(momentum10 / 0.05)
rsi     = clamp((RSI14 - 50) / 20)
price   = clamp((underlying price - SMA20) / ATR14)

signed score = 0.30*trend + 0.25*macd + 0.20*momentum + 0.15*rsi + 0.10*price
signal score = abs(signed score)
```

A candidate is emitted only when:

- data age is within `MARKET_MAX_DATA_AGE_SECONDS`;
- `volume_ratio_20` is at least `OPPORTUNITY_MIN_VOLUME_RATIO`; and
- the absolute score is at least `OPPORTUNITY_SIGNAL_THRESHOLD`.

The sign determines `bullish` or `bearish`. Human-readable reasons list only evidence aligned
with that direction. This candidate is analysis output, not authorization to trade.

## Configuration

```env
MARKET_WATCHLIST=SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMD
MARKET_SCAN_LOOKBACK_DAYS=180
MARKET_MAX_DATA_AGE_SECONDS=345600
OPPORTUNITY_SIGNAL_THRESHOLD=0.35
OPPORTUNITY_MIN_VOLUME_RATIO=0.75
```

The four-day default freshness window accommodates weekends and exchange holidays for daily bars.
Later execution phases must apply a much tighter quote-freshness rule before any order.

## Development endpoint

`GET /api/v1/market/opportunities` performs a read-only scan. Without Alpaca paper credentials it
returns the configured watchlist and an empty opportunity set without making an external request.
With credentials, it reads Alpaca market data but has no dependency on the broker execution API.
