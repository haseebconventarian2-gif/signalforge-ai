from fastapi import APIRouter

from app.api.dependencies import (
    AgentDependency,
    ControlAuthorizationDependency,
    SettingsDependency,
)
from app.core.exceptions import ConflictError
from app.domain.agent import AgentRuntimeStatus

router = APIRouter()


@router.get("/status", response_model=AgentRuntimeStatus)
async def status(agent: AgentDependency) -> AgentRuntimeStatus:
    return agent.status()


@router.post("/start", response_model=AgentRuntimeStatus)
async def start(agent: AgentDependency, _: ControlAuthorizationDependency) -> AgentRuntimeStatus:
    return await agent.start()


@router.post("/pause", response_model=AgentRuntimeStatus)
async def pause(agent: AgentDependency, _: ControlAuthorizationDependency) -> AgentRuntimeStatus:
    return await agent.pause()


@router.post("/scan", response_model=AgentRuntimeStatus)
async def scan(agent: AgentDependency, _: ControlAuthorizationDependency) -> AgentRuntimeStatus:
    return await agent.run_once()


@router.post("/kill-switch", response_model=AgentRuntimeStatus)
async def kill(agent: AgentDependency, _: ControlAuthorizationDependency) -> AgentRuntimeStatus:
    return await agent.activate_kill_switch()


@router.post("/kill-switch/reset", response_model=AgentRuntimeStatus)
async def reset_kill(
    agent: AgentDependency, _: ControlAuthorizationDependency
) -> AgentRuntimeStatus:
    return await agent.reset_kill_switch()


@router.post("/demo/run", response_model=AgentRuntimeStatus)
async def demo_run(
    agent: AgentDependency,
    settings: SettingsDependency,
    _: ControlAuthorizationDependency,
) -> AgentRuntimeStatus:
    if not settings.demo_mode:
        raise ConflictError("Set DEMO_MODE=true to enable the real-component demo trigger")
    return await agent.run_once()
