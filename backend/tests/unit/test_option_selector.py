from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from app.domain.broker import OptionContract, OptionSnapshot, OptionType, Quote
from app.domain.reasoning import TradeRecommendation
from app.services.option_selector import OptionContractSelector
from tests.unit.test_reasoning_models import valid_recommendation
from tests.unit.test_reasoning_service import candidate


def contract(
    symbol: str, strike: str, *, option_type: OptionType = OptionType.CALL
) -> OptionContract:
    return OptionContract(
        id=uuid4(),
        symbol=symbol,
        name=symbol,
        status="active",
        tradable=True,
        expiration_date=date(2026, 9, 24),
        root_symbol="SPY",
        underlying_symbol="SPY",
        type=option_type,
        style="american",
        strike_price=Decimal(strike),
    )


def snapshot(symbol: str, bid: str, ask: str, *, size: str = "10") -> OptionSnapshot:
    return OptionSnapshot(
        symbol=symbol,
        latest_quote=Quote(
            timestamp=datetime(2026, 9, 3, 16, tzinfo=UTC),
            bid_price=Decimal(bid),
            ask_price=Decimal(ask),
            bid_size=Decimal(size),
            ask_size=Decimal(size),
        ),
    )


def selector() -> OptionContractSelector:
    return OptionContractSelector(
        min_dte=7,
        max_dte=35,
        target_dte=21,
        max_spread_pct=Decimal("0.15"),
        max_strike_distance_pct=Decimal("0.10"),
        min_bid_size=Decimal("1"),
        min_ask_size=Decimal("1"),
    )


def test_selects_highest_scored_real_alpaca_contract() -> None:
    contracts = (contract("SPY_ATM", "103"), contract("SPY_OTM", "108"))
    snapshots = (snapshot("SPY_ATM", "4.90", "5.10"), snapshot("SPY_OTM", "2.50", "2.70"))
    recommendation = TradeRecommendation.model_validate(valid_recommendation())

    result = selector().select(
        candidate(),
        recommendation,
        contracts,
        snapshots,
        as_of=date(2026, 9, 3),
        maximum_capital=Decimal("750"),
    )

    assert result.selected is not None
    assert result.selected.contract.symbol == "SPY_ATM"
    assert result.selected.premium_per_contract == 510
    assert result.selected.score.total > 0


def test_rejects_wrong_direction_wide_spread_and_unaffordable_contracts() -> None:
    contracts = (
        contract("SPY_PUT", "103", option_type=OptionType.PUT),
        contract("SPY_WIDE", "103"),
        contract("SPY_COSTLY", "103"),
    )
    snapshots = (
        snapshot("SPY_PUT", "4.90", "5.10"),
        snapshot("SPY_WIDE", "1", "2"),
        snapshot("SPY_COSTLY", "9.90", "10.10"),
    )

    result = selector().select(
        candidate(),
        TradeRecommendation.model_validate(valid_recommendation()),
        contracts,
        snapshots,
        as_of=date(2026, 9, 3),
        maximum_capital=Decimal("750"),
    )

    assert result.selected is None
    assert result.rejected_contracts == 3
