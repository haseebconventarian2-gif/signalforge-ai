from __future__ import annotations

from http import HTTPStatus
from typing import Any


class SignalForgeError(Exception):
    """Base class for expected domain and application failures."""

    code = "SIGNALFORGE_ERROR"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    title = "SignalForge error"

    def __init__(self, detail: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context = context or {}


class ConfigurationError(SignalForgeError):
    code = "CONFIGURATION_ERROR"
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    title = "Invalid application configuration"


class PaperTradingViolation(ConfigurationError):
    code = "PAPER_TRADING_VIOLATION"
    title = "Paper-trading safety violation"


class DatabaseUnavailableError(SignalForgeError):
    code = "DATABASE_UNAVAILABLE"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    title = "Database unavailable"


class ResourceNotFoundError(SignalForgeError):
    code = "RESOURCE_NOT_FOUND"
    status_code = HTTPStatus.NOT_FOUND
    title = "Resource not found"


class ConflictError(SignalForgeError):
    code = "CONFLICT"
    status_code = HTTPStatus.CONFLICT
    title = "Resource conflict"


class PositionReconciliationRequiredError(ConflictError):
    code = "POSITION_RECONCILIATION_REQUIRED"
    title = "Position reconciliation required"


class ControlAuthenticationError(SignalForgeError):
    code = "CONTROL_AUTHENTICATION_REQUIRED"
    status_code = HTTPStatus.UNAUTHORIZED
    title = "Control authentication required"


class ControlUnavailableError(SignalForgeError):
    code = "CONTROL_API_DISABLED"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    title = "Control API disabled"


class ExternalServiceError(SignalForgeError):
    code = "EXTERNAL_SERVICE_ERROR"
    status_code = HTTPStatus.BAD_GATEWAY
    title = "External service error"


class BrokerError(ExternalServiceError):
    code = "BROKER_ERROR"
    title = "Broker request failed"


class BrokerAuthenticationError(BrokerError):
    code = "BROKER_AUTHENTICATION_ERROR"
    title = "Broker authentication failed"


class BrokerPermissionError(BrokerError):
    code = "BROKER_PERMISSION_ERROR"
    title = "Broker permission denied"


class BrokerRateLimitError(BrokerError):
    code = "BROKER_RATE_LIMIT"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    title = "Broker rate limit reached"


class BrokerTimeoutError(BrokerError):
    code = "BROKER_TIMEOUT"
    status_code = HTTPStatus.GATEWAY_TIMEOUT
    title = "Broker request timed out"


class BrokerValidationError(BrokerError):
    code = "BROKER_VALIDATION_ERROR"
    title = "Broker rejected invalid data"


class BrokerOrderRejectedError(BrokerError):
    code = "BROKER_ORDER_REJECTED"
    title = "Paper order rejected"


class AmbiguousOrderSubmissionError(BrokerError):
    code = "AMBIGUOUS_ORDER_SUBMISSION"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    title = "Paper order submission state is unknown"


class OrderSubmissionDisabledError(BrokerError):
    code = "ORDER_SUBMISSION_DISABLED"
    status_code = HTTPStatus.CONFLICT
    title = "Paper order submission is disabled"


class IndicatorCalculationError(SignalForgeError):
    code = "INDICATOR_CALCULATION_ERROR"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    title = "Market indicators could not be calculated"


class LLMError(ExternalServiceError):
    code = "LLM_ERROR"
    title = "LLM reasoning failed"


class LLMConfigurationError(LLMError):
    code = "LLM_NOT_CONFIGURED"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    title = "LLM is not configured"


class LLMTimeoutError(LLMError):
    code = "LLM_TIMEOUT"
    status_code = HTTPStatus.GATEWAY_TIMEOUT
    title = "LLM request timed out"


class LLMRateLimitError(LLMError):
    code = "LLM_RATE_LIMIT"
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    title = "LLM rate limit reached"


class LLMResponseValidationError(LLMError):
    code = "LLM_INVALID_RESPONSE"
    title = "LLM response failed validation"


class LLMInputTooLargeError(LLMError):
    code = "LLM_INPUT_TOO_LARGE"
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    title = "LLM input exceeds the configured limit"
