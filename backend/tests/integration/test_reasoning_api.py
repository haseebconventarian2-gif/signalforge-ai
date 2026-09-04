from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_reasoning_service


class FakeReasoningService:
    async def evaluate(self, candidate):
        return {
            "id": str(uuid4()),
            "recommendation": {
                "symbol": candidate.symbol,
                "decision": "NO_TRADE",
                "confidence": "0",
                "market_bias": "neutral",
                "thesis": "No trade because validation evidence is intentionally unavailable.",
                "supporting_factors": ["Candidate was schema validated"],
                "risk_factors": ["Mocked reasoning response"],
                "preferred_moneyness": "ATM",
                "minimum_days_to_expiry": 7,
                "maximum_days_to_expiry": 35,
            },
            "metadata": {
                "model": "mock-model",
                "prompt_version": "trading-reasoner-v1",
                "schema_version": "trade-recommendation-v1",
                "latency_ms": 0,
                "input_characters": 10,
                "validation_status": "failed_closed",
                "failure_code": "TEST",
            },
        }


def test_reasoning_endpoint_has_no_broker_execution_dependency(client: TestClient) -> None:
    client.app.dependency_overrides[get_reasoning_service] = lambda: FakeReasoningService()
    payload = {
        "symbol": "SPY",
        "timestamp": "2026-09-03T16:00:00Z",
        "data_timestamp": "2026-09-03T15:59:00Z",
        "underlying_price": "103",
        "directional_bias": "bullish",
        "signal_score": "0.75",
        "indicator_snapshot": {
            "period_return": "0.01",
            "sma_20": "100",
            "ema_20": "102",
            "ema_50": "100",
            "rsi_14": "60",
            "macd": "1",
            "macd_signal": "0.5",
            "macd_histogram": "0.5",
            "atr_14": "2",
            "volume_ratio_20": "1.3",
            "annualized_volatility_20": "0.2",
            "recent_high_20": "105",
            "recent_low_20": "95",
            "momentum_10": "0.04",
            "trend_strength": "1",
        },
        "reasons": ["Deterministic signal"],
        "data_freshness_seconds": 60,
    }

    response = client.post("/api/v1/reasoning/evaluate", json=payload)

    assert response.status_code == 200
    assert response.json()["recommendation"]["decision"] == "NO_TRADE"
    assert response.json()["metadata"]["failure_code"] == "TEST"
    client.app.dependency_overrides.clear()
