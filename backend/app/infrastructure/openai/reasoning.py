from __future__ import annotations

from pathlib import Path
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
    RateLimitError,
)
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import (
    LLMConfigurationError,
    LLMError,
    LLMRateLimitError,
    LLMResponseValidationError,
    LLMTimeoutError,
)
from app.domain.reasoning import ProviderReasoningResult, TradeRecommendation

PROMPT_VERSION = "trading-reasoner-v1"
SCHEMA_VERSION = "trade-recommendation-v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / "trading_reasoner_v1.txt"


class OpenAIResponsesReasoningProvider:
    """OpenAI Responses adapter using SDK-enforced Pydantic Structured Outputs."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client
        if client is None and settings.openai_configured:
            api_key = settings.openai_api_key
            if api_key is None:  # Defensive; openai_configured already proves this is set.
                raise LLMConfigurationError("OpenAI API key is not configured")
            client_options: dict[str, Any] = {
                "api_key": api_key.get_secret_value(),
                "timeout": settings.openai_request_timeout_seconds,
                "max_retries": settings.openai_max_retries,
            }
            if settings.llm_base_url is not None:
                client_options["base_url"] = settings.llm_base_url
            self._client = AsyncOpenAI(
                **client_options,
            )
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    async def evaluate(self, candidate_json: str) -> ProviderReasoningResult:
        if self._client is None:
            raise LLMConfigurationError("OpenAI API key is not configured")
        try:
            response = await self._client.responses.parse(
                model=self._settings.llm_model,
                input=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": candidate_json},
                ],
                text_format=TradeRecommendation,
                store=False,
            )
        except APITimeoutError as exc:
            raise LLMTimeoutError("OpenAI request timed out") from exc
        except RateLimitError as exc:
            raise LLMRateLimitError("OpenAI rate limit reached") from exc
        except (ValidationError, ValueError) as exc:
            raise LLMResponseValidationError("OpenAI output did not match the schema") from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise LLMError("OpenAI request failed") from exc
        except OpenAIError as exc:
            raise LLMResponseValidationError("OpenAI did not return a usable response") from exc

        recommendation = response.output_parsed
        if not isinstance(recommendation, TradeRecommendation):
            raise LLMResponseValidationError("OpenAI returned no validated recommendation")
        usage = getattr(response, "usage", None)
        return ProviderReasoningResult(
            recommendation=recommendation,
            response_id=getattr(response, "id", None),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
