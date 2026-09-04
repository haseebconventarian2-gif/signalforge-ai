# SignalForge

SignalForge is an autonomous AI options research and Alpaca paper-trading platform. It scans a
configurable market universe, computes deterministic signals, requests a schema-validated OpenAI
recommendation, applies final-authority risk rules, selects a real Alpaca option contract, and
persists the full lifecycle for the React operations console.

The default configuration is deliberately inert: scheduled autonomy, demo mode, and order
submission are all disabled. SignalForge rejects live Alpaca endpoints at startup.

## Architecture

The project is a typed modular monolith:

- `backend/app/domain`: provider-independent trading models and protocols
- `backend/app/services`: scanner, reasoning, risk, selection, execution, monitoring, orchestration
- `backend/app/infrastructure`: Alpaca, OpenAI, PostgreSQL, and read-only Alpaca CLI adapters
- `backend/app/api`: REST and WebSocket delivery
- `frontend`: responsive React/TypeScript operations console
- `backend/alembic`: versioned PostgreSQL/Supabase schema

The guarded entry pipeline is:

`scan -> AI recommendation -> preliminary risk -> contract selection -> final risk -> persisted intent -> Alpaca paper order`

The LLM cannot choose a contract, size an order, submit an order, or override a failed risk rule.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and safety invariants.

## Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 17+ or a Supabase PostgreSQL connection
- Alpaca paper credentials
- OpenAI API key for AI evaluation

## Local setup

From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
npm.cmd --prefix frontend install
Set-Location backend
alembic upgrade head
uvicorn app.main:app --reload --port 8002
```

In a second terminal:

```powershell
Set-Location frontend
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. API documentation is at
`http://127.0.0.1:8002/api/v1/docs`.

For Supabase, copy the SQLAlchemy connection string from **Project Settings > Database** and use
the transaction-pooler URL when IPv6 is unavailable. Keep `ssl=require` in the query string.

## Safety switches

Keep these defaults while validating the installation:

```env
ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets
ALPACA_LIVE_TRADE=false
ORDER_SUBMISSION_ENABLED=false
AGENT_AUTONOMY_ENABLED=false
DEMO_MODE=false
RISK_KILL_SWITCH=false
```

To permit autonomous paper orders, review all risk values first, verify the paper account in the
dashboard, then set both `ORDER_SUBMISSION_ENABLED=true` and `AGENT_AUTONOMY_ENABLED=true` and
restart the API. There is no live endpoint configuration supported by this codebase.

## Quality checks

```powershell
Set-Location backend
ruff format --check app tests
ruff check app tests alembic
mypy app
pytest
alembic check

Set-Location ..\frontend
npm.cmd run lint
npm.cmd run build
npm.cmd run visual-check
```

All automated broker and OpenAI tests use fakes. The visual check uses local Microsoft Edge by
default and writes ignored screenshots to `frontend/test-results`.

## Docker

`docker compose up --build` runs a local PostgreSQL container, migrations, FastAPI, and the Nginx
frontend at `http://127.0.0.1:3000`. The Compose database override intentionally uses local
PostgreSQL rather than the Supabase URL in `.env`.

## Operations and demo

- [docs/OPERATIONS.md](docs/OPERATIONS.md): startup, controls, recovery, and failure behavior
- [docs/DEMO.md](docs/DEMO.md): repeatable judge walkthrough without fake success records
- [docs/ALPACA_CLI.md](docs/ALPACA_CLI.md): read-only CLI integration and isolation boundary
- [docs/LLM_REASONING.md](docs/LLM_REASONING.md): structured-output contract and fail-closed policy
- [docs/MARKET_INTELLIGENCE.md](docs/MARKET_INTELLIGENCE.md): indicator formulas and scanner rules

## Known limitations

- This is a hackathon-grade single-account system, not a multi-tenant brokerage product.
- Runtime controls are intended for a localhost or trusted private network and do not implement
  user authentication. Do not expose the backend directly to the public internet.
- Entry fills returned after the initial submission response require a later reconciliation pass;
  automated periodic reconciliation of every nonterminal order is not yet a durable worker.
- Positions opened outside SignalForge are visible through Alpaca but are not automatically adopted
  into the managed local lifecycle.
- Performance metrics are operational records, not evidence of future profitability.
