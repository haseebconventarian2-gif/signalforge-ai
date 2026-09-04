from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from app.domain.reasoning import TradeDecision
from app.domain.risk import (
    RiskContext,
    RiskDecision,
    RiskLimits,
    RiskRuleEvaluation,
    RiskStage,
    RiskVerdict,
)


class RiskEngine:
    """Pure deterministic final authority for entry risk."""

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def evaluate(self, context: RiskContext) -> RiskDecision:
        checks: list[RiskRuleEvaluation] = []
        add = checks.append
        add(
            self._check(
                "KILL_SWITCH",
                not context.kill_switch_active,
                context.kill_switch_active,
                False,
                "Emergency kill switch must be inactive",
            )
        )
        add(
            self._check(
                "MARKET_OPEN", context.market_open, context.market_open, True, "Market must be open"
            )
        )
        action_allowed = context.recommendation.decision in {
            TradeDecision.BUY_CALL,
            TradeDecision.BUY_PUT,
        }
        add(
            self._check(
                "ACTION_ALLOWED",
                action_allowed,
                context.recommendation.decision.value,
                "BUY_CALL|BUY_PUT",
                "Recommendation must request a supported long option",
            )
        )
        direction_matches = (
            context.recommendation.decision is TradeDecision.BUY_CALL
            and context.candidate.directional_bias.value == "bullish"
        ) or (
            context.recommendation.decision is TradeDecision.BUY_PUT
            and context.candidate.directional_bias.value == "bearish"
        )
        add(
            self._check(
                "DIRECTION_MATCH",
                direction_matches,
                context.recommendation.decision.value,
                context.candidate.directional_bias.value,
                "Recommendation must agree with deterministic directional bias",
            )
        )
        add(
            self._check(
                "MIN_AI_CONFIDENCE",
                context.recommendation.confidence >= self.limits.min_ai_confidence,
                context.recommendation.confidence,
                self.limits.min_ai_confidence,
                "AI confidence must meet the configured floor",
            )
        )
        daily_limit = context.equity * self.limits.max_daily_loss_pct
        add(
            self._check(
                "DAILY_LOSS_LIMIT",
                context.daily_realized_pnl > -daily_limit,
                context.daily_realized_pnl,
                -daily_limit,
                "Realized daily loss must remain above the loss limit",
            )
        )
        add(
            self._check(
                "CONSECUTIVE_LOSSES",
                context.consecutive_losses < self.limits.max_consecutive_losses,
                context.consecutive_losses,
                self.limits.max_consecutive_losses,
                "Consecutive loss limit must not be reached",
            )
        )
        cooldown_passed = (
            context.cooldown_until is None or context.observed_at >= context.cooldown_until
        )
        add(
            self._check(
                "LOSS_COOLDOWN",
                cooldown_passed,
                context.cooldown_until or "none",
                "expired",
                "Loss cooldown must have expired",
            )
        )
        add(
            self._check(
                "DUPLICATE_TRADE",
                not context.duplicate_trade,
                context.duplicate_trade,
                False,
                "No active candidate, order, or position may duplicate this underlying",
            )
        )
        add(
            self._check(
                "MAX_OPEN_POSITIONS",
                context.open_position_count < self.limits.max_open_positions,
                context.open_position_count,
                self.limits.max_open_positions,
                "Open position count must remain below the limit",
            )
        )
        portfolio_limit = context.equity * self.limits.max_portfolio_exposure_pct
        add(
            self._check(
                "PORTFOLIO_EXPOSURE",
                context.total_options_exposure < portfolio_limit,
                context.total_options_exposure,
                portfolio_limit,
                "Options exposure must remain below the portfolio cap",
            )
        )
        underlying_limit = context.equity * self.limits.max_underlying_exposure_pct
        add(
            self._check(
                "UNDERLYING_EXPOSURE",
                context.underlying_exposure < underlying_limit,
                context.underlying_exposure,
                underlying_limit,
                "Underlying exposure must remain below its cap",
            )
        )
        add(
            self._check(
                "MIN_VOLUME_RATIO",
                context.candidate.indicator_snapshot.volume_ratio_20
                >= self.limits.min_volume_ratio,
                context.candidate.indicator_snapshot.volume_ratio_20,
                self.limits.min_volume_ratio,
                "Underlying volume ratio must meet the minimum",
            )
        )

        if context.stage is RiskStage.FINAL:
            checks.extend(self._final_checks(context))
        else:
            for name in (
                "QUOTE_FRESHNESS",
                "BID_ASK_SPREAD",
                "MIN_LIQUIDITY",
                "DTE",
                "PREMIUM_LIMIT",
                "POSITION_SIZE",
            ):
                add(
                    self._check(
                        name,
                        True,
                        "deferred",
                        "final stage",
                        "Contract-specific rule deferred until selection",
                    )
                )

        maximum_capital = self._maximum_capital(context)
        quantity = 0
        if (
            context.stage is RiskStage.FINAL
            and context.contract_premium
            and context.contract_premium > 0
        ):
            quantity = int(
                (maximum_capital / context.contract_premium).to_integral_value(rounding=ROUND_FLOOR)
            )
        passed = all(check.passed for check in checks) and (
            context.stage is RiskStage.PRELIMINARY or quantity > 0
        )
        return RiskDecision(
            verdict=RiskVerdict.APPROVED if passed else RiskVerdict.REJECTED,
            stage=context.stage,
            evaluations=tuple(checks),
            approved_quantity=quantity if passed else 0,
            maximum_capital=maximum_capital,
        )

    def _final_checks(self, context: RiskContext) -> tuple[RiskRuleEvaluation, ...]:
        quote_age = (
            max(0, int((context.observed_at - context.quote_timestamp).total_seconds()))
            if context.quote_timestamp
            else None
        )
        midpoint = (
            (context.bid + context.ask) / 2
            if context.bid is not None and context.ask is not None and context.ask > 0
            else None
        )
        spread = (
            (context.ask - context.bid) / midpoint
            if midpoint and context.bid is not None and context.ask is not None and midpoint > 0
            else None
        )
        quote_valid = quote_age is not None and quote_age <= self.limits.max_quote_age_seconds
        spread_valid = (
            spread is not None and Decimal("0") <= spread <= self.limits.max_bid_ask_spread_pct
        )
        liquidity_valid = (
            context.bid_size is not None
            and context.ask_size is not None
            and context.bid_size >= 1
            and context.ask_size >= 1
        )
        dte_valid = (
            context.dte is not None and self.limits.min_dte <= context.dte <= self.limits.max_dte
        )
        premium_valid = (
            context.contract_premium is not None
            and context.contract_premium <= self.limits.max_premium_per_trade
        )
        capital = self._maximum_capital(context)
        size_valid = (
            context.contract_premium is not None
            and context.contract_premium > 0
            and capital >= context.contract_premium
        )
        return (
            self._check(
                "QUOTE_FRESHNESS",
                quote_valid,
                quote_age if quote_age is not None else "missing",
                self.limits.max_quote_age_seconds,
                "Option quote must be present and fresh",
            ),
            self._check(
                "BID_ASK_SPREAD",
                spread_valid,
                spread if spread is not None else "missing",
                self.limits.max_bid_ask_spread_pct,
                "Bid/ask spread must be within the configured maximum",
            ),
            self._check(
                "MIN_LIQUIDITY",
                liquidity_valid,
                f"{context.bid_size}/{context.ask_size}",
                "1/1",
                "Both sides of the option quote require displayed size",
            ),
            self._check(
                "DTE",
                dte_valid,
                context.dte if context.dte is not None else "missing",
                f"{self.limits.min_dte}-{self.limits.max_dte}",
                "Expiration must be inside the allowed DTE window",
            ),
            self._check(
                "PREMIUM_LIMIT",
                premium_valid,
                context.contract_premium if context.contract_premium is not None else "missing",
                self.limits.max_premium_per_trade,
                "One contract must fit under the premium cap",
            ),
            self._check(
                "POSITION_SIZE",
                size_valid,
                context.contract_premium if context.contract_premium is not None else "missing",
                capital,
                "At least one contract must fit all capital constraints",
            ),
        )

    def _maximum_capital(self, context: RiskContext) -> Decimal:
        return max(
            Decimal("0"),
            min(
                context.equity * self.limits.max_risk_per_trade_pct,
                self.limits.max_premium_per_trade,
                context.options_buying_power,
                (context.equity * self.limits.max_portfolio_exposure_pct)
                - context.total_options_exposure,
                (context.equity * self.limits.max_underlying_exposure_pct)
                - context.underlying_exposure,
            ),
        )

    @staticmethod
    def _check(
        name: str, passed: bool, actual: object, limit: object, reason: str
    ) -> RiskRuleEvaluation:
        return RiskRuleEvaluation(
            rule_name=name, passed=passed, actual_value=str(actual), limit=str(limit), reason=reason
        )
