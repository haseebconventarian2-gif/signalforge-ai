from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.domain.broker import OptionContract, OptionSnapshot, OptionType
from app.domain.market_intelligence import CandidateOpportunity
from app.domain.options import ContractScore, ContractSelectionResult, SelectedOptionContract
from app.domain.reasoning import MoneynessPreference, TradeDecision, TradeRecommendation


class OptionContractSelector:
    """Filter and score only contracts returned by the broker contract master."""

    def __init__(
        self,
        *,
        min_dte: int,
        max_dte: int,
        target_dte: int,
        max_spread_pct: Decimal,
        max_strike_distance_pct: Decimal,
        min_bid_size: Decimal,
        min_ask_size: Decimal,
    ) -> None:
        self._min_dte = min_dte
        self._max_dte = max_dte
        self._target_dte = target_dte
        self._max_spread_pct = max_spread_pct
        self._max_strike_distance_pct = max_strike_distance_pct
        self._min_bid_size = min_bid_size
        self._min_ask_size = min_ask_size

    def select(
        self,
        candidate: CandidateOpportunity,
        recommendation: TradeRecommendation,
        contracts: tuple[OptionContract, ...],
        snapshots: tuple[OptionSnapshot, ...],
        *,
        as_of: date,
        maximum_capital: Decimal,
    ) -> ContractSelectionResult:
        required_type = (
            OptionType.CALL if recommendation.decision is TradeDecision.BUY_CALL else OptionType.PUT
        )
        if recommendation.decision is TradeDecision.NO_TRADE:
            return ContractSelectionResult(
                rejected_contracts=len(contracts), reason="Recommendation is NO_TRADE"
            )
        snapshot_by_symbol = {item.symbol: item for item in snapshots}
        eligible: list[SelectedOptionContract] = []
        for contract in contracts:
            snapshot = snapshot_by_symbol.get(contract.symbol)
            selection = self._score(
                candidate, recommendation, contract, snapshot, required_type, as_of, maximum_capital
            )
            if selection:
                eligible.append(selection)
        if not eligible:
            return ContractSelectionResult(
                rejected_contracts=len(contracts),
                reason=(
                    "No contract passed direction, DTE, liquidity, spread, distance, "
                    "and capital filters"
                ),
            )
        eligible.sort(key=lambda item: (-item.score.total, item.contract.symbol))
        return ContractSelectionResult(
            selected=eligible[0],
            rejected_contracts=len(contracts) - len(eligible),
            reason="Selected highest deterministic contract score",
        )

    def _score(
        self,
        candidate: CandidateOpportunity,
        recommendation: TradeRecommendation,
        contract: OptionContract,
        snapshot: OptionSnapshot | None,
        required_type: OptionType,
        as_of: date,
        maximum_capital: Decimal,
    ) -> SelectedOptionContract | None:
        if (
            not contract.tradable
            or contract.status != "active"
            or contract.type is not required_type
        ):
            return None
        dte = (contract.expiration_date - as_of).days
        min_dte = max(self._min_dte, recommendation.minimum_days_to_expiry)
        max_dte = min(self._max_dte, recommendation.maximum_days_to_expiry)
        if not min_dte <= dte <= max_dte or snapshot is None or snapshot.latest_quote is None:
            return None
        quote = snapshot.latest_quote
        if quote.bid_price <= 0 or quote.ask_price <= quote.bid_price:
            return None
        midpoint = (quote.bid_price + quote.ask_price) / 2
        spread = (quote.ask_price - quote.bid_price) / midpoint
        premium = quote.ask_price * 100
        strike_distance = (
            abs(contract.strike_price - candidate.underlying_price) / candidate.underlying_price
        )
        if (
            spread > self._max_spread_pct
            or strike_distance > self._max_strike_distance_pct
            or quote.bid_size < self._min_bid_size
            or quote.ask_size < self._min_ask_size
            or premium > maximum_capital
        ):
            return None

        moneyness = Decimal("35") * (Decimal("1") - strike_distance / self._max_strike_distance_pct)
        preference_match = self._preference_matches(
            recommendation.preferred_moneyness,
            required_type,
            contract.strike_price,
            candidate.underlying_price,
        )
        if preference_match:
            moneyness = min(Decimal("35"), moneyness + Decimal("5"))
        liquidity = Decimal("15") * min(Decimal("1"), quote.bid_size / Decimal("10")) + Decimal(
            "15"
        ) * min(Decimal("1"), quote.ask_size / Decimal("10"))
        spread_score = Decimal("25") * (Decimal("1") - spread / self._max_spread_pct)
        expiry_distance = Decimal(abs(dte - self._target_dte))
        expiry_score = Decimal("10") * max(
            Decimal("0"),
            Decimal("1") - expiry_distance / Decimal(max(1, self._max_dte - self._min_dte)),
        )
        total = moneyness + liquidity + spread_score + expiry_score
        score = ContractScore(
            symbol=contract.symbol,
            total=total.quantize(Decimal("0.0001")),
            moneyness_score=moneyness.quantize(Decimal("0.0001")),
            liquidity_score=liquidity.quantize(Decimal("0.0001")),
            spread_score=spread_score.quantize(Decimal("0.0001")),
            expiry_score=expiry_score.quantize(Decimal("0.0001")),
            explanation=(
                f"strike distance {strike_distance:.4f}",
                f"spread {spread:.4f}",
                f"DTE {dte}",
                f"ask premium ${premium:.2f}",
            ),
        )
        return SelectedOptionContract(
            contract=contract,
            snapshot=snapshot,
            midpoint=midpoint,
            spread_percentage=spread,
            premium_per_contract=premium,
            days_to_expiry=dte,
            score=score,
        )

    @staticmethod
    def _preference_matches(
        preference: MoneynessPreference,
        option_type: OptionType,
        strike: Decimal,
        underlying: Decimal,
    ) -> bool:
        if preference is MoneynessPreference.ATM:
            return abs(strike - underlying) / underlying <= Decimal("0.02")
        is_itm = (option_type is OptionType.CALL and strike < underlying) or (
            option_type is OptionType.PUT and strike > underlying
        )
        return is_itm if preference is MoneynessPreference.SLIGHTLY_ITM else not is_itm
