from fastapi import APIRouter

from app.api.routes.agent import router as agent_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.api.routes.integrations import router as integrations_router
from app.api.routes.market import router as market_router
from app.api.routes.reasoning import router as reasoning_router

api_router = APIRouter()
api_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(events_router, tags=["events"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(integrations_router, prefix="/integrations", tags=["integrations"])
api_router.include_router(market_router, prefix="/market", tags=["market intelligence"])
api_router.include_router(reasoning_router, prefix="/reasoning", tags=["AI reasoning"])
