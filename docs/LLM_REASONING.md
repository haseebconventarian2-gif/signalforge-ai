# LLM Reasoning

Phase 4 adds a schema-constrained advisory reasoning layer. It uses the OpenAI Responses API and
the Python SDK's Pydantic Structured Outputs parser. It cannot access the broker, size a position,
select an option symbol, approve risk, or submit an order.

Official references:

- [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
- [Responses API](https://platform.openai.com/docs/api-reference/responses)

## Boundary

`OpenAIResponsesReasoningProvider` receives one compact JSON serialization of a typed
`CandidateOpportunity`. System instructions and candidate data are separate messages. The system
prompt explicitly treats every candidate field as untrusted data and rejects instructions embedded
inside it.

The provider calls `responses.parse` with `TradeRecommendation` as `text_format`. Free-form text is
never parsed for execution advice and malformed JSON is never repaired. The schema forbids unknown
fields and supports only:

- `BUY_CALL`
- `BUY_PUT`
- `NO_TRADE`

The model returns only directional advice, confidence, thesis, factors, moneyness preference, and a
DTE window. It cannot return contract symbols, strikes, prices, quantities, or order parameters.

## Fail-closed policy

The application converts every unsafe outcome into a persisted `NO_TRADE` decision with zero
confidence:

- missing API configuration;
- timeout or rate limit;
- connection or provider error;
- refusal, truncation, content filtering, or absent parsed output;
- schema validation failure;
- candidate/recommendation symbol mismatch; or
- input exceeding `OPENAI_MAX_INPUT_CHARS`.

SDK retries are bounded by `OPENAI_MAX_RETRIES` and occur before any execution intent exists.

## Audit storage

Migration `20260903_0002` creates `ai_decisions`. Each attempt stores:

- sanitized candidate snapshot and SHA-256 fingerprint;
- validated recommendation or generated fail-closed recommendation;
- model, provider response ID, prompt version, and schema version;
- latency, input size, and token usage when available; and
- validation status and stable failure code.

API keys, raw provider responses, authentication headers, and hidden reasoning are never stored.
Provider-side response storage is disabled with `store=False`.

## Configuration

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_DEPLOYMENT=
OPENAI_REQUEST_TIMEOUT_SECONDS=30
OPENAI_MAX_RETRIES=1
OPENAI_MAX_INPUT_CHARS=12000
```

For Azure OpenAI, keep the Azure resource key in `OPENAI_API_KEY`, set
`AZURE_OPENAI_ENDPOINT` to the resource endpoint, and set
`AZURE_OPENAI_DEPLOYMENT` to the deployment name. The adapter uses Azure's
`/openai/v1/` endpoint automatically. When the Azure values are blank, it uses
the standard OpenAI endpoint and `OPENAI_MODEL`.

The model name is configurable and recorded with every decision. The default is a project choice,
not a claim that it is the newest model available to every account.

## API

`POST /api/v1/reasoning/evaluate` accepts a strict `CandidateOpportunity`, evaluates it, persists
the result, and returns `ReasoningDecision`. This route has no broker dependency. Until application
authentication is implemented, expose it only on a trusted local development interface because a
configured OpenAI call can incur usage charges.
