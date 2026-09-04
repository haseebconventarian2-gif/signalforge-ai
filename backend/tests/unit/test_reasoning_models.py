from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.reasoning import TradeRecommendation


def valid_recommendation() -> dict[str, object]:
    return {
        "symbol": "SPY",
        "decision": "BUY_CALL",
        "confidence": Decimal("0.81"),
        "market_bias": "bullish",
        "thesis": "Trend and momentum evidence align while defined risks remain material.",
        "supporting_factors": ["EMA trend is positive"],
        "risk_factors": ["Volatility may reverse abruptly"],
        "preferred_moneyness": "ATM",
        "minimum_days_to_expiry": 14,
        "maximum_days_to_expiry": 30,
    }


def test_recommendation_rejects_extra_fields_and_unsupported_actions() -> None:
    payload = valid_recommendation()
    payload["decision"] = "SELL_NAKED_CALL"
    payload["quantity"] = 100

    with pytest.raises(ValidationError):
        TradeRecommendation.model_validate(payload)


def test_recommendation_rejects_invalid_confidence_and_expiry_window() -> None:
    payload = valid_recommendation()
    payload["confidence"] = Decimal("1.01")
    payload["minimum_days_to_expiry"] = 40
    payload["maximum_days_to_expiry"] = 20

    with pytest.raises(ValidationError):
        TradeRecommendation.model_validate(payload)


def test_recommendation_normalizes_factors_without_accepting_blanks() -> None:
    payload = valid_recommendation()
    payload["supporting_factors"] = ["  positive trend  "]
    result = TradeRecommendation.model_validate(payload)
    assert result.supporting_factors == ("positive trend",)

    payload["supporting_factors"] = ["   "]
    with pytest.raises(ValidationError):
        TradeRecommendation.model_validate(payload)
