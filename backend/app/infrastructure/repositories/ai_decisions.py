from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.market_intelligence import CandidateOpportunity
from app.domain.reasoning import ReasoningDecision
from app.infrastructure.database.models import AIDecisionRecord


class AIDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        candidate: CandidateOpportunity,
        decision: ReasoningDecision,
        *,
        candidate_json: str,
        candidate_id: UUID | None = None,
    ) -> UUID:
        record = AIDecisionRecord(
            id=decision.id,
            symbol=candidate.symbol,
            candidate_id=candidate_id,
            candidate_fingerprint=sha256(candidate_json.encode("utf-8")).hexdigest(),
            decision=decision.recommendation.decision.value,
            confidence=decision.recommendation.confidence,
            candidate_snapshot=candidate.model_dump(mode="json"),
            recommendation=decision.recommendation.model_dump(mode="json"),
            model=decision.metadata.model,
            provider_response_id=decision.metadata.provider_response_id,
            prompt_version=decision.metadata.prompt_version,
            schema_version=decision.metadata.schema_version,
            latency_ms=decision.metadata.latency_ms,
            input_characters=decision.metadata.input_characters,
            input_tokens=decision.metadata.input_tokens,
            output_tokens=decision.metadata.output_tokens,
            validation_status=decision.metadata.validation_status,
            failure_code=decision.metadata.failure_code,
        )
        self._session.add(record)
        await self._session.commit()
        return record.id
