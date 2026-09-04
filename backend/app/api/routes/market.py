from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.dependencies import BrokerDependency, MarketScannerDependency, SettingsDependency
from app.domain.market_intelligence import MarketScanResult

router = APIRouter()


@router.get("/opportunities", response_model=MarketScanResult)
async def scan_opportunities(
    settings: SettingsDependency,
    scanner: MarketScannerDependency,
    broker: BrokerDependency,
) -> MarketScanResult:
    """Run a read-only deterministic scan; this path cannot create orders."""
    if not settings.alpaca_credentials_configured:
        return MarketScanResult(
            timestamp=datetime.now(UTC),
            watchlist=settings.watchlist_symbols,
            opportunities=(),
        )
    result = await scanner.scan()
    clock = await broker.get_market_clock()
    return result.model_copy(update={"market_open": clock.is_open})
