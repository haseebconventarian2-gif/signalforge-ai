from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.exceptions import DatabaseUnavailableError


class Database:
    """Owns the async SQLAlchemy engine and session factory."""

    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 5,
        pool_timeout_seconds: float = 10.0,
        transaction_pooler: bool = False,
    ) -> None:
        engine_options: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
        if transaction_pooler:
            engine_options.update(
                poolclass=NullPool,
                connect_args={
                    "statement_cache_size": 0,
                    "prepared_statement_cache_size": 0,
                    "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
                },
            )
        elif not url.startswith("sqlite"):
            engine_options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout_seconds,
            )
        self.engine = create_async_engine(url, **engine_options)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def ping(self) -> None:
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise DatabaseUnavailableError("Database connectivity check failed") from exc

    async def dispose(self) -> None:
        await self.engine.dispose()
