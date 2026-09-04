# Operations Runbook

## Startup order

1. Confirm `.env` points to an Alpaca paper account and PostgreSQL/Supabase.
2. Leave `ORDER_SUBMISSION_ENABLED=false` for connectivity and UI checks.
3. From `backend`, run `alembic upgrade head` and then
   `uvicorn app.main:app --reload --port 8002`.
4. From `frontend`, run `npm.cmd run dev` and open `http://127.0.0.1:5173`.
5. Check `/api/v1/health/ready`, the PAPER TRADING badge, account equity, and execution status.

The API fails startup for a live/unknown trading URL, incomplete Alpaca credentials, a non-Postgres
production database, or incompatible risk settings.

## Runtime controls

- **Start** schedules bounded scan cycles only when `AGENT_AUTONOMY_ENABLED=true`.
- **Pause** prevents new scheduled scans while position monitoring continues.
- **Run scan** executes one bounded cycle. With submission disabled it can still use market data and
  OpenAI, persist candidates, run both risk stages, and select contracts.
- **Kill switch** blocks new entries and asks the deterministic monitor to close managed paper
  positions. It never enables live trading.
- **Reset kill switch** returns the runtime to stopped; it does not start the agent.

Control routes are not authenticated in this release. Bind the service to localhost or place it
behind authenticated private ingress.

## Failure behavior

- Invalid or unavailable LLM output is persisted as `NO_TRADE`.
- Read requests use bounded retries for transient Alpaca failures.
- Order POSTs are never blindly retried. An ambiguous response is persisted as
  `UNKNOWN_RECONCILIATION_REQUIRED` and looked up by deterministic client order ID.
- A stale quote, closed market, failed rule, missing contract, or failed audit write blocks entry.
- Candidate and symbol locks prevent overlapping cycles and duplicate work in one process.
- Every cycle error is isolated, logged without secrets, and exposed as an error class in agent
  status rather than terminating the scheduler.

## Recovery

After an unclean shutdown:

1. Restart with `ORDER_SUBMISSION_ENABLED=false`.
2. Compare local orders in Trade History with Alpaca paper orders.
3. Resolve any `SUBMITTING`, `PARTIALLY_FILLED`, or `UNKNOWN_RECONCILIATION_REQUIRED` record by its
   `client_order_id`; never submit a replacement before the lookup.
4. Compare managed positions with the Alpaca account and resolve external/unmanaged positions.
5. Run `alembic current` and `alembic check`.
6. Re-enable paper submission only after local and broker state agree.

## Incident response

Activate the kill switch for a strategy or data-integrity incident. If provider state is uncertain,
leave submission disabled and inspect Alpaca directly. Rotate any credential that has been pasted,
logged, or otherwise exposed, then update `.env` and restart the processes.
