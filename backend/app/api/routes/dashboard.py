from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.dependencies import BrokerDependency, SessionDependency, SettingsDependency
from app.infrastructure.database.models import (
    AIDecisionRecord,
    JournalEvent,
    OptionSelectionRecord,
    OrderRecord,
    PositionRecord,
    RiskDecisionRecord,
    TradeCandidateRecord,
)

router = APIRouter()


@router.get("/configuration")
async def configuration(settings: SettingsDependency) -> dict[str, Any]:
    return {
        "watchlist": settings.watchlist_symbols,
        "scan_interval_seconds": settings.agent_scan_interval_seconds,
        "signal_threshold": settings.opportunity_signal_threshold,
        "minimum_ai_confidence": settings.risk_min_ai_confidence,
        "maximum_risk_per_trade_pct": settings.risk_max_risk_per_trade_pct,
        "maximum_premium_per_trade": settings.risk_max_premium_per_trade,
        "maximum_open_positions": settings.risk_max_open_positions,
        "maximum_spread_pct": settings.risk_max_bid_ask_spread_pct,
        "dte_window": [settings.risk_min_dte, settings.risk_max_dte],
        "stop_loss_pct": settings.exit_stop_loss_pct,
        "take_profit_pct": settings.exit_take_profit_pct,
        "paper_trading": True,
        "demo_mode": settings.demo_mode,
    }


@router.get("/overview")
async def overview(
    settings: SettingsDependency,
    broker: BrokerDependency,
    session: SessionDependency,
) -> dict[str, Any]:
    positions = tuple(
        (
            await session.execute(select(PositionRecord).where(PositionRecord.status == "OPEN"))
        ).scalars()
    )
    closed = tuple(
        (
            await session.execute(select(PositionRecord).where(PositionRecord.status == "CLOSED"))
        ).scalars()
    )
    realized = sum((item.realized_pnl or Decimal("0") for item in closed), Decimal("0"))
    wins = sum(1 for item in closed if item.realized_pnl is not None and item.realized_pnl > 0)
    account = await broker.get_account() if settings.alpaca_credentials_configured else None
    unrealized = sum(
        (
            ((item.current_price or item.entry_price) - item.entry_price) * item.quantity * 100
            for item in positions
        ),
        Decimal("0"),
    )
    return {
        "paper_trading": True,
        "equity": account.equity if account else Decimal("0"),
        "cash": account.cash if account else Decimal("0"),
        "buying_power": account.buying_power if account else Decimal("0"),
        "options_buying_power": account.options_buying_power if account else None,
        "daily_pnl": realized,
        "total_pnl": realized + unrealized,
        "win_rate": Decimal(wins) / len(closed) if closed else Decimal("0"),
        "open_positions": len(positions),
        "execution_enabled": settings.order_submission_enabled,
    }


@router.get("/positions")
async def positions(session: SessionDependency) -> list[dict[str, Any]]:
    records = tuple(
        (
            await session.execute(select(PositionRecord).order_by(PositionRecord.created_at.desc()))
        ).scalars()
    )
    return [
        {
            "id": item.id,
            "underlying": item.underlying_symbol,
            "contract_symbol": item.contract_symbol,
            "status": item.status,
            "quantity": item.quantity,
            "entry_price": item.entry_price,
            "current_price": item.current_price,
            "unrealized_pnl": (
                ((item.current_price or item.entry_price) - item.entry_price) * item.quantity * 100
            ),
            "stop_price": item.stop_price,
            "target_price": item.target_price,
            "expiration_date": item.expiration_date,
            "opened_at": item.opened_at,
            "closed_at": item.closed_at,
            "realized_pnl": item.realized_pnl,
            "exit_reason": item.exit_reason,
        }
        for item in records
    ]


@router.get("/orders")
async def orders(
    session: SessionDependency, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, Any]]:
    records = tuple(
        (
            await session.execute(
                select(OrderRecord).order_by(OrderRecord.created_at.desc()).limit(limit)
            )
        ).scalars()
    )
    return [
        {
            "id": item.id,
            "candidate_id": item.candidate_id,
            "contract_symbol": item.contract_symbol,
            "underlying": item.underlying_symbol,
            "intent": item.intent,
            "status": item.status,
            "quantity": item.quantity,
            "filled_quantity": item.filled_quantity,
            "limit_price": item.limit_price,
            "average_fill_price": item.average_fill_price,
            "client_order_id": item.client_order_id,
            "created_at": item.created_at,
        }
        for item in records
    ]


@router.get("/candidates")
async def candidates(
    session: SessionDependency, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, Any]]:
    records = tuple(
        (
            await session.execute(
                select(TradeCandidateRecord)
                .order_by(TradeCandidateRecord.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    result: list[dict[str, Any]] = []
    for item in records:
        ai = (
            await session.execute(
                select(AIDecisionRecord)
                .where(AIDecisionRecord.candidate_id == item.id)
                .order_by(AIDecisionRecord.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        risks = tuple(
            (
                await session.execute(
                    select(RiskDecisionRecord)
                    .where(RiskDecisionRecord.candidate_id == item.id)
                    .order_by(RiskDecisionRecord.created_at)
                )
            ).scalars()
        )
        contract = (
            await session.execute(
                select(OptionSelectionRecord)
                .where(OptionSelectionRecord.candidate_id == item.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        result.append(
            {
                "id": item.id,
                "correlation_id": item.correlation_id,
                "symbol": item.symbol,
                "status": item.status,
                "direction": item.direction,
                "signal_score": item.signal_score,
                "snapshot": item.snapshot,
                "reasons": item.reasons.get("items", []),
                "created_at": item.created_at,
                "ai_decision": ai.recommendation if ai else None,
                "ai_metadata": (
                    {
                        "model": ai.model,
                        "validation_status": ai.validation_status,
                        "failure_code": ai.failure_code,
                    }
                    if ai
                    else None
                ),
                "risk_decisions": [
                    {
                        "stage": risk.stage,
                        "verdict": risk.verdict,
                        "evaluations": risk.evaluations.get("items", []),
                    }
                    for risk in risks
                ],
                "contract": (
                    {
                        "symbol": contract.contract_symbol,
                        "type": contract.option_type,
                        "strike": contract.strike_price,
                        "expiration": contract.expiration_date,
                        "premium": contract.premium,
                        "score": contract.score,
                    }
                    if contract
                    else None
                ),
            }
        )
    return result


@router.get("/candidates/{candidate_id}")
async def candidate_timeline(candidate_id: UUID, session: SessionDependency) -> dict[str, Any]:
    candidate = await session.get(TradeCandidateRecord, candidate_id)
    if candidate is None:
        return {"candidate": None, "timeline": []}
    ai = tuple(
        (
            await session.execute(
                select(AIDecisionRecord).where(AIDecisionRecord.candidate_id == candidate_id)
            )
        ).scalars()
    )
    risks = tuple(
        (
            await session.execute(
                select(RiskDecisionRecord).where(RiskDecisionRecord.candidate_id == candidate_id)
            )
        ).scalars()
    )
    contracts = tuple(
        (
            await session.execute(
                select(OptionSelectionRecord).where(
                    OptionSelectionRecord.candidate_id == candidate_id
                )
            )
        ).scalars()
    )
    orders = tuple(
        (
            await session.execute(
                select(OrderRecord).where(OrderRecord.candidate_id == candidate_id)
            )
        ).scalars()
    )
    timeline: list[dict[str, Any]] = [
        {
            "stage": "MARKET_SIGNAL",
            "timestamp": candidate.created_at,
            "status": candidate.status,
            "details": candidate.snapshot,
        }
    ]
    timeline.extend(
        {
            "stage": "AI_DECISION",
            "timestamp": item.created_at,
            "status": item.decision,
            "details": item.recommendation,
        }
        for item in ai
    )
    timeline.extend(
        {
            "stage": f"RISK_{item.stage}",
            "timestamp": item.created_at,
            "status": item.verdict,
            "details": item.evaluations,
        }
        for item in risks
    )
    timeline.extend(
        {
            "stage": "CONTRACT_SELECTION",
            "timestamp": item.observed_at,
            "status": item.contract_symbol,
            "details": item.score,
        }
        for item in contracts
    )
    timeline.extend(
        {
            "stage": "ORDER",
            "timestamp": item.created_at,
            "status": item.status,
            "details": {"client_order_id": item.client_order_id},
        }
        for item in orders
    )
    timeline.sort(key=lambda item: item["timestamp"])
    return {"candidate": candidate.snapshot, "timeline": timeline}


@router.get("/journal")
async def journal(
    session: SessionDependency, limit: int = Query(default=100, ge=1, le=500)
) -> list[dict[str, Any]]:
    records = tuple(
        (
            await session.execute(
                select(JournalEvent).order_by(JournalEvent.created_at.desc()).limit(limit)
            )
        ).scalars()
    )
    return [
        {
            "id": item.id,
            "correlation_id": item.correlation_id,
            "candidate_id": item.candidate_id,
            "event_type": item.event_type,
            "severity": item.severity,
            "message": item.message,
            "details": item.details,
            "created_at": item.created_at,
        }
        for item in records
    ]


@router.get("/analytics")
async def analytics(session: SessionDependency) -> dict[str, Any]:
    positions = tuple(
        (
            await session.execute(select(PositionRecord).where(PositionRecord.status == "CLOSED"))
        ).scalars()
    )
    candidates = tuple((await session.execute(select(TradeCandidateRecord))).scalars())
    pnl = [item.realized_pnl or Decimal("0") for item in positions]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    by_symbol: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in positions:
        by_symbol[item.underlying_symbol] += item.realized_pnl or Decimal("0")
    rejection_counts = Counter(item.status for item in candidates if "REJECTED" in item.status)
    ai_records = tuple((await session.execute(select(AIDecisionRecord))).scalars())
    position_by_candidate = {}
    for item in positions:
        if item.candidate_id is not None:
            position_by_candidate[item.candidate_id] = item
    confidence_buckets: dict[str, list[Decimal]] = defaultdict(list)
    for decision in ai_records:
        if decision.candidate_id is None:
            continue
        position = position_by_candidate.get(decision.candidate_id)
        if position is None:
            continue
        confidence = decision.confidence
        bucket = (
            "0.9-1.0"
            if confidence >= Decimal("0.9")
            else "0.8-0.9"
            if confidence >= Decimal("0.8")
            else "0.7-0.8"
            if confidence >= Decimal("0.7")
            else "below-0.7"
        )
        confidence_buckets[bucket].append(position.realized_pnl or Decimal("0"))
    cumulative = Decimal("0")
    curve = []
    for item in sorted(positions, key=lambda value: value.closed_at or value.created_at):
        cumulative += item.realized_pnl or Decimal("0")
        curve.append({"timestamp": item.closed_at or item.created_at, "pnl": cumulative})
    return {
        "trades": len(positions),
        "win_rate": Decimal(len(wins)) / len(pnl) if pnl else Decimal("0"),
        "average_win": sum(wins, Decimal("0")) / len(wins) if wins else Decimal("0"),
        "average_loss": sum(losses, Decimal("0")) / len(losses) if losses else Decimal("0"),
        "profit_factor": (
            sum(wins, Decimal("0")) / abs(sum(losses, Decimal("0"))) if losses else None
        ),
        "cumulative_pnl": curve,
        "by_symbol": dict(by_symbol),
        "rejections": dict(rejection_counts),
        "by_confidence": {
            bucket: {
                "trades": len(values),
                "pnl": sum(values, Decimal("0")),
            }
            for bucket, values in confidence_buckets.items()
        },
    }
