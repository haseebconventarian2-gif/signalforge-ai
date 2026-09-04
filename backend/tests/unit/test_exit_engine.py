from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.monitoring import ExitPolicy, ExitReason, PositionState
from app.services.monitoring import ExitEngine

NOW = datetime(2026, 9, 4, 16, tzinfo=UTC)


def engine() -> ExitEngine:
    return ExitEngine(
        ExitPolicy(
            stop_loss_pct=Decimal("0.35"),
            take_profit_pct=Decimal("0.60"),
            maximum_holding_days=10,
            exit_dte=2,
        )
    )


def position(**overrides) -> PositionState:
    values = {
        "contract_symbol": "SPY260925C00100000",
        "underlying_symbol": "SPY",
        "quantity": 1,
        "entry_price": Decimal("5"),
        "current_price": Decimal("5"),
        "opened_at": NOW - timedelta(days=1),
        "expiration_date": date(2026, 9, 25),
    }
    values.update(overrides)
    return PositionState.model_validate(values)


@pytest.mark.parametrize(
    ("overrides", "kill_switch", "reason"),
    [
        ({}, True, ExitReason.KILL_SWITCH),
        ({"current_price": Decimal("3.25")}, False, ExitReason.STOP_LOSS),
        ({"current_price": Decimal("8")}, False, ExitReason.TAKE_PROFIT),
        ({"expiration_date": date(2026, 9, 6)}, False, ExitReason.EXPIRY),
        ({"opened_at": NOW - timedelta(days=10)}, False, ExitReason.MAX_HOLD),
        ({"signal_reversed": True}, False, ExitReason.SIGNAL_REVERSAL),
    ],
)
def test_exit_rules_are_deterministic(
    overrides: dict, kill_switch: bool, reason: ExitReason
) -> None:
    result = engine().evaluate(
        position(**overrides), observed_at=NOW, kill_switch_active=kill_switch
    )

    assert result.should_exit is True
    assert result.reason is reason


def test_position_remains_open_when_no_rule_matches() -> None:
    result = engine().evaluate(position(), observed_at=NOW, kill_switch_active=False)

    assert result.should_exit is False
    assert result.reason is ExitReason.NONE
