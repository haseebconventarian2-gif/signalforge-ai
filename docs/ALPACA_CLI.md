# Alpaca CLI Integration

SignalForge uses the Alpaca CLI as an independent, read-only verification path for the hackathon.
The application adapter runs one fixed command: `alpaca account get --quiet`.

Before launching the subprocess it supplies the exact paper origin and server-side credentials via
the CLI's `APCA_API_*` environment variables. It uses `create_subprocess_exec` without a shell,
accepts no user-provided arguments, has a strict timeout, does not return command output containing
account details, and exposes only a normalized status at `GET /api/v1/integrations/alpaca-cli`.

The CLI is deliberately excluded from execution. All order creation remains inside the typed broker
adapter and must pass persisted intent, deterministic risk approval, contract validation,
freshness checks, idempotency, and the explicit paper-submission switch.

If the CLI is absent, the endpoint reports `installed=false` without affecting the core agent. This
keeps optional judge verification separate from normal service availability.
