from __future__ import annotations


class ServiceError(Exception):
    """Application-level error with HTTP status code and machine-readable error code."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: str = "SERVICE_ERROR",
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.error_code = error_code
        super().__init__(detail)


class LLMRequestError(ServiceError):
    """LLM service call failed."""

    def __init__(self, detail: str = "LLM request failed", *, cause: str = "") -> None:
        super().__init__(502, detail, error_code="LLM_REQUEST_FAILED")
        self.cause = cause


class LLMCircuitOpenError(ServiceError):
    """Circuit breaker is open — LLM calls are temporarily blocked."""

    def __init__(self) -> None:
        super().__init__(
            503,
            "AI service is temporarily unavailable, please retry shortly",
            error_code="LLM_CIRCUIT_OPEN",
        )
