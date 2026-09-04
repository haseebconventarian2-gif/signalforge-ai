# Deployment

SignalForge uses a split deployment:

- Vercel hosts the static React/Vite frontend.
- An always-on container host runs FastAPI, the autonomous scheduler, and WebSockets.
- Supabase remains the PostgreSQL database.

## Backend

Deploy `backend/Dockerfile` from the repository root to a container platform such as Azure
Container Apps, Render, Railway, or Fly.io. Run exactly one application replica because the event
hub and scheduler lifecycle are process-local. The container applies Alembic migrations before
starting Uvicorn and uses the platform-provided `PORT`.

Copy the values from the local `.env` into the backend platform's secret/environment settings. Do
not commit `.env`. Set this value to the final Vercel production URL:

```env
CORS_ALLOWED_ORIGINS=https://your-project.vercel.app
```

Confirm the deployed backend before proceeding:

```text
https://your-backend.example/api/v1/health/live
https://your-backend.example/api/v1/health/ready
```

## Frontend on Vercel

Import the Git repository into Vercel and configure:

```text
Root Directory: frontend
Framework Preset: Vite
Build Command: npm run build
Output Directory: dist
```

Add these Vercel environment variables for Production and Preview as appropriate:

```env
VITE_API_BASE_URL=https://your-backend.example
VITE_WS_BASE_URL=wss://your-backend.example
```

Deploy the frontend, then update `CORS_ALLOWED_ORIGINS` on the backend to the exact final Vercel
URL and restart the backend. Add each preview origin explicitly if preview deployments need API
access; wildcard origins are intentionally rejected.

## Verification

Open the Vercel URL and verify:

1. The sidebar reports `Realtime connected`.
2. Overview loads the Alpaca paper balance.
3. Scanner returns the configured watchlist.
4. Agent controls accept `CONTROL_API_TOKEN`.
5. Browser developer tools show no CORS or WebSocket errors.
