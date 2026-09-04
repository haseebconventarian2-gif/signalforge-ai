from enum import StrEnum


class AgentStatus(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    KILLED = "KILLED"
    DEGRADED = "DEGRADED"


class AgentRunStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunTrigger(StrEnum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"
    RECOVERY = "RECOVERY"


class JournalSeverity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
