# Hackathon Demo

SignalForge demo mode invokes the real scanner, OpenAI adapter, risk engine, Alpaca contract data,
selector, persistence, and paper execution service. It does not insert synthetic success records.

## Preparation

1. Use a dedicated Alpaca paper account with options enabled.
2. Confirm the market-data feed available to that account.
3. Apply migrations and run all quality checks from the README.
4. Start with `ORDER_SUBMISSION_ENABLED=false`, `AGENT_AUTONOMY_ENABLED=false`, and
   `DEMO_MODE=true`.
5. Open the dashboard and verify account data, PAPER TRADING, and Realtime connected.

## Walkthrough

1. Show Configuration: watchlist, interval, DTE range, confidence threshold, exposure limits, and
   disabled execution switch.
2. Open Scanner and run a bounded scan.
3. Open AI Decisions to follow signal, structured recommendation, individual risk evaluations,
   Alpaca-derived contract selection, and final status.
4. Select a candidate timeline to show its persisted discovery-to-outcome lifecycle.
5. Show rejected candidates as first-class audit results rather than hiding them.
6. Show Trade History, Positions, and analytics. Empty states are honest when no paper fills exist.
7. Call `GET /api/v1/integrations/alpaca-cli` to demonstrate the independent read-only paper-account
   verifier when the official CLI is installed.

## Paper-order demonstration

Only after checking the paper account and risk settings, restart with
`ORDER_SUBMISSION_ENABLED=true`. Keep the paper URL exact. Run one scan, show the persisted intent
before submission, then show the paper order result. Return submission to `false` after the demo.

Market conditions may produce no candidate, an AI `NO_TRADE`, or a risk rejection. Those are valid
real outcomes. Do not lower safeguards merely to manufacture a fill.
