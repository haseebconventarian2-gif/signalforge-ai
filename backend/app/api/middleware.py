from __future__ import annotations

import time
from uuid import uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.logging import bind_request_id, reset_request_id

logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid4()))[:128]
        request.state.request_id = request_id
        token = bind_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            await logger.ainfo(
                "http_request",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return response
        finally:
            reset_request_id(token)
