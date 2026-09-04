from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.exceptions import LLMRateLimitError
from app.domain.market_intelligence import (
    CandidateOpportunity,
    DirectionalBias,
    IndicatorSnapshot,
)
from app.domain.reasoning import ProviderReasoningResult, TradeDecision, TradeRecommendation
from app.infrastructure.database.models import AIDecisionRecord
from app.infrastructure.repositories.ai_decisions import AIDecisionRepository
from app.services.reasoning import ReasoningService
from tests.unit.test_reasoning_models import valid_recommendation


def candidate(*, symbol: str = "SPY", reason: str = "Deterministic signal") -> CandidateOpportunity:
    return CandidateOpportunity(
        symbol=symbol,
        timestamp=datetime(2026, 9, 3, 16, tzinfo=UTC),
        data_timestamp=datetime(2026, 9, 3, 15, 59, tzinfo=UTC),
        underlying_price=Decimal("103"),
        directional_bias=DirectionalBias.BULLISH,
        signal_score=Decimal("0.75"),
        indicator_snapshot=IndicatorSnapshot(
            period_return=Decimal("0.01"),
            sma_20=Decimal("100"),
            ema_20=Decimal("102"),
            ema_50=Decimal("100"),
            rsi_14=Decimal("60"),
            macd=Decimal("1"),
            macd_signal=Decimal("0.5"),
            macd_histogram=Decimal("0.5"),
            atr_14=Decimal("2"),
            volume_ratio_20=Decimal("1.3"),
            annualized_volatility_20=Decimal("0.2"),
            recent_high_20=Decimal("105"),
            recent_low_20=Decimal("95"),
            momentum_10=Decimal("0.04"),
            trend_strength=Decimal("1"),
        ),
        reasons=(reason,),
        data_freshness_seconds=60,
    )


class FakeProvider:
    def __init__(
        self, result: ProviderReasoningResult | None = None, error: Exception | None = None
    ):
        self.result = result
        self.error = error

    async def evaluate(self, candidate_json: str) -> ProviderReasoningResult:
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result

    async def close(self) -> None:
        return None


async def test_valid_decision_and_metadata_are_persisted(database) -> None:
    recommendation = TradeRecommendation.model_validate(valid_recommendation())
    provider = FakeProvider(
        ProviderReasoningResult(
            recommendation=recommendation,
            response_id="resp_123",
            input_tokens=120,
            output_tokens=60,
        )
    )
    async with database.session_factory() as session:
        service = ReasoningService(
            provider,
            AIDecisionRepository(session),
            model="test-model",
            maximum_input_characters=12_000,
        )
        result = await service.evaluate(candidate())

        record = (await session.execute(select(AIDecisionRecord))).scalar_one()
        assert result.recommendation.decision is TradeDecision.BUY_CALL
        assert result.metadata.validation_status == "validated"
        assert record.provider_response_id == "resp_123"
        assert record.input_tokens == 120
        assert record.recommendation["decision"] == "BUY_CALL"
        assert "api_key" not in str(record.candidate_snapshot).lower()


@pytest.mark.parametrize(
    ("provider", "expected_code"),
    [
        (FakeProvider(error=LLMRateLimitError("rate limited")), "LLM_RATE_LIMIT"),
        (
            FakeProvider(
                ProviderReasoningResult(
                    recommendation=TradeRecommendation.model_validate(
                        {**valid_recommendation(), "symbol": "QQQ"}
                    )
                )
            ),
            "LLM_INVALID_RESPONSE",
        ),
    ],
)
async def test_provider_failure_and_symbol_mismatch_fail_closed_and_persist(
    database, provider: FakeProvider, expected_code: str
) -> None:
    async with database.session_factory() as session:
        service = ReasoningService(
            provider,
            AIDecisionRepository(session),
            model="test-model",
            maximum_input_characters=12_000,
        )
        result = await service.evaluate(candidate())

        record = (await session.execute(select(AIDecisionRecord))).scalar_one()
        assert result.recommendation.decision is TradeDecision.NO_TRADE
        assert result.recommendation.confidence == 0
        assert result.metadata.failure_code == expected_code
        assert record.validation_status == "failed_closed"
        assert record.failure_code == expected_code


async def test_oversized_input_never_reaches_provider(database) -> None:
    provider = FakeProvider()
    async with database.session_factory() as session:
        service = ReasoningService(
            provider,
            AIDecisionRepository(session),
            model="test-model",
            maximum_input_characters=100,
        )
        result = await service.evaluate(candidate(reason="x" * 500))

    assert result.recommendation.decision is TradeDecision.NO_TRADE
    assert result.metadata.failure_code == "LLM_INPUT_TOO_LARGE"
