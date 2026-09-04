from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/events")
async def events(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin", "").rstrip("/")
    if origin not in websocket.app.state.settings.cors_origins:
        await websocket.close(code=1008, reason="Origin is not allowed")
        return
    await websocket.accept()
    hub = websocket.app.state.events
    try:
        async with hub.subscribe() as queue:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    await websocket.send_json(event)
                except TimeoutError:
                    await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        return
