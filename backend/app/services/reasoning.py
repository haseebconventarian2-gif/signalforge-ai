from __future__ import annotations

import json
from decimal import Decimal
from time import perf_counter
from uuid import UUID, uuid4

from app.core.exceptions import LLMError, LLMInputTooLargeError, LLMResponseValidationError
from app.domain.market_intelligence import CandidateOpportunity
from app.domain.reasoning import (
    DecisionMetadata,
    LLMReasoningProvider,
    MarketBias,
    MoneynessPreference,
    ReasoningDecision,
    TradeDecision,
    TradeRecommendation,
)
from app.infrastructure.openai.reasoning import PROMPT_VERSION, SCHEMA_VERSION
from app.infrastructure.repositories.ai_decisions import AIDecisionRepository


class ReasoningService:
    """Validate, fail closed, and persist every model reasoning attempt."""

    def __init__(
        self,
        provider: LLMReasoningProvider,
        repository: AIDecisionRepository,
        *,
        model: str,
        maximum_input_characters: int,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._model = model
        self._maximum_input_characters = maximum_input_characters

    async def evaluate(
        self, candidate: CandidateOpportunity, *, candidate_id: UUID | None = None
    ) -> ReasoningDecision:
        candidate_json = json.dumps(
            candidate.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        started = perf_counter()
        try:
            if len(candidate_json) > self._maximum_input_characters:
                raise LLMInputTooLargeError(
                    "Candidate input exceeds the configured character limit"
                )
            provider_result = await self._provider.evaluate(candidate_json)
            if provider_result.recommendation.symbol != candidate.symbol:
                raise LLMResponseValidationError("Recommendation symbol does not match candidate")
            recommendation = provider_result.recommendation
            response_id = provider_result.response_id
            input_tokens = provider_result.input_tokens
            output_tokens = provider_result.output_tokens
            validation_status = "validated"
            failure_code = None
        except LLMError as exc:
            recommendation = self._no_trade(candidate.symbol, exc.code)
            response_id = None
            input_tokens = None
            output_tokens = None
            validation_status = "failed_closed"
            failure_code = exc.code

        decision = ReasoningDecision(
            id=uuid4(),
            recommendation=recommendation,
            metadata=DecisionMetadata(
                model=self._model,
                provider_response_id=response_id,
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                input_characters=len(candidate_json),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                validation_status=validation_status,
                failure_code=failure_code,
            ),
        )
        await self._repository.save(
            candidate,
            decision,
            candidate_json=candidate_json,
            candidate_id=candidate_id,
        )
        return decision

    @staticmethod
    def _no_trade(symbol: str, failure_code: str) -> TradeRecommendation:
        return TradeRecommendation(
            symbol=symbol,
            decision=TradeDecision.NO_TRADE,
            confidence=Decimal("0"),
            market_bias=MarketBias.NEUTRAL,
            thesis="No trade because the model response was not safely validated.",
            supporting_factors=("No validated supporting factors are available.",),
            risk_factors=(f"Reasoning failure: {failure_code}",),
            preferred_moneyness=MoneynessPreference.ATM,
            minimum_days_to_expiry=7,
            maximum_days_to_expiry=35,
        )
