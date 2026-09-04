from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.domain.enums import AgentRunStatus, JournalSeverity, RunTrigger
from app.infrastructure.database.models import AgentConfiguration, AgentRun, JournalEvent
from app.infrastructure.database.session import Database


async def test_foundation_models_round_trip(database: Database) -> None:
    async with database.session_factory() as session:
        configuration = AgentConfiguration(version=1, active=True, strategy={}, risk={})
        run = AgentRun(
            configuration=configuration,
            status=AgentRunStatus.STARTED,
            trigger=RunTrigger.MANUAL,
            started_at=datetime.now(UTC),
        )
        event = JournalEvent(
            correlation_id=uuid4(),
            run=run,
            event_type="RUN_STARTED",
            severity=JournalSeverity.INFO,
            message="Foundation test event",
            details={"paper_trading": True},
        )
        session.add(event)
        await session.commit()

    async with database.session_factory() as session:
        stored = (await session.scalars(select(JournalEvent))).one()
        assert stored.event_type == "RUN_STARTED"
        assert stored.details == {"paper_trading": True}
