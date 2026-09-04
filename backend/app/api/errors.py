from __future__ import annotations

from uuid import uuid4

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.exceptions import SignalForgeError

logger = structlog.get_logger(__name__)


async def signalforge_error_handler(request: Request, exc: SignalForgeError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    await logger.awarning(
        "application_error",
        error_code=exc.code,
        path=request.url.path,
        context=exc.context,
    )
    return JSONResponse(
        status_code=int(exc.status_code),
        media_type="application/problem+json",
        content={
            "type": f"urn:signalforge:error:{exc.code.lower()}",
            "title": exc.title,
            "status": int(exc.status_code),
            "detail": exc.detail,
            "code": exc.code,
            "instance": request.url.path,
            "request_id": request_id,
        },
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    await logger.aexception("unexpected_error", path=request.url.path)
    return JSONResponse(
        status_code=500,
        media_type="application/problem+json",
        content={
            "type": "urn:signalforge:error:internal_server_error",
            "title": "Internal server error",
            "status": 500,
            "detail": "An unexpected error occurred",
            "code": "INTERNAL_SERVER_ERROR",
            "instance": request.url.path,
            "request_id": request_id,
        },
    )
