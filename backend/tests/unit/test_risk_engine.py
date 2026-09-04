from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.reasoning import TradeRecommendation
from app.domain.risk import RiskContext, RiskLimits, RiskStage, RiskVerdict
from app.services.risk_engine import RiskEngine
from tests.unit.test_reasoning_models import valid_recommendation
from tests.unit.test_reasoning_service import candidate

NOW = datetime(2026, 9, 3, 16, tzinfo=UTC)


def limits() -> RiskLimits:
    return RiskLimits(
        max_risk_per_trade_pct=Decimal("0.01"),
        max_premium_per_trade=Decimal("750"),
        max_portfolio_exposure_pct=Decimal("0.05"),
        max_open_positions=4,
        max_underlying_exposure_pct=Decimal("0.02"),
        min_ai_confidence=Decimal("0.72"),
        max_daily_loss_pct=Decimal("0.02"),
        max_consecutive_losses=3,
        cooldown_minutes=30,
        max_quote_age_seconds=15,
        min_volume_ratio=Decimal("0.75"),
        max_bid_ask_spread_pct=Decimal("0.15"),
        min_dte=7,
        max_dte=35,
    )


def context(**overrides) -> RiskContext:
    values = {
        "candidate": candidate(),
        "recommendation": TradeRecommendation.model_validate(valid_recommendation()),
        "stage": RiskStage.FINAL,
        "observed_at": NOW,
        "equity": Decimal("100000"),
        "options_buying_power": Decimal("50000"),
        "total_options_exposure": Decimal("1000"),
        "underlying_exposure": Decimal("0"),
        "open_position_count": 1,
        "daily_realized_pnl": Decimal("0"),
        "consecutive_losses": 0,
        "market_open": True,
        "quote_timestamp": NOW - timedelta(seconds=5),
        "bid": Decimal("4.90"),
        "ask": Decimal("5.10"),
        "bid_size": Decimal("10"),
        "ask_size": Decimal("10"),
        "dte": 21,
        "contract_premium": Decimal("510"),
    }
    values.update(overrides)
    return RiskContext.model_validate(values)


def test_final_approval_sizes_from_tightest_capital_limit() -> None:
    decision = RiskEngine(limits()).evaluate(context())

    assert decision.verdict is RiskVerdict.APPROVED
    assert decision.maximum_capital == 750
    assert decision.approved_quantity == 1
    assert all(item.passed for item in decision.evaluations)


@pytest.mark.parametrize(
    ("override", "rule"),
    [
        ({"kill_switch_active": True}, "KILL_SWITCH"),
        ({"market_open": False}, "MARKET_OPEN"),
        ({"duplicate_trade": True}, "DUPLICATE_TRADE"),
        ({"open_position_count": 4}, "MAX_OPEN_POSITIONS"),
        ({"daily_realized_pnl": Decimal("-2000")}, "DAILY_LOSS_LIMIT"),
        ({"consecutive_losses": 3}, "CONSECUTIVE_LOSSES"),
        ({"cooldown_until": NOW + timedelta(minutes=1)}, "LOSS_COOLDOWN"),
        ({"quote_timestamp": NOW - timedelta(seconds=16)}, "QUOTE_FRESHNESS"),
        ({"bid": Decimal("4"), "ask": Decimal("6")}, "BID_ASK_SPREAD"),
        ({"bid_size": Decimal("0")}, "MIN_LIQUIDITY"),
        ({"dte": 36}, "DTE"),
        ({"contract_premium": Decimal("751")}, "PREMIUM_LIMIT"),
        ({"options_buying_power": Decimal("100")}, "POSITION_SIZE"),
    ],
)
def test_each_boundary_rejects_with_rule_evidence(override: dict, rule: str) -> None:
    decision = RiskEngine(limits()).evaluate(context(**override))

    assert decision.verdict is RiskVerdict.REJECTED
    failed = {item.rule_name for item in decision.evaluations if not item.passed}
    assert rule in failed


def test_preliminary_stage_defers_contract_rules_but_never_system_rules() -> None:
    preliminary = context(
        stage=RiskStage.PRELIMINARY,
        quote_timestamp=None,
        bid=None,
        ask=None,
        bid_size=None,
        ask_size=None,
        dte=None,
        contract_premium=None,
    )
    decision = RiskEngine(limits()).evaluate(preliminary)

    assert decision.verdict is RiskVerdict.APPROVED
    assert decision.approved_quantity == 0
    assert all(item.passed for item in decision.evaluations)
