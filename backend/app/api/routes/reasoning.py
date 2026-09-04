from fastapi import APIRouter

from app.api.dependencies import ReasoningServiceDependency
from app.domain.market_intelligence import CandidateOpportunity
from app.domain.reasoning import ReasoningDecision

router = APIRouter()


@router.post("/evaluate", response_model=ReasoningDecision)
async def evaluate_candidate(
    candidate: CandidateOpportunity,
    service: ReasoningServiceDependency,
) -> ReasoningDecision:
    """Evaluate and audit a candidate; this endpoint has no broker dependency."""
    return await service.evaluate(candidate)
