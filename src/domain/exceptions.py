"""Domain and application errors.

Each error carries a stable ``code`` and an HTTP status used by the API layer.
Messages are generic on purpose: they must never leak policies, prompts or
internal configuration to the client.
"""


class AppError(Exception):
    code = "unexpected_error"
    http_status = 500
    public_message = "Unexpected error"

    def __init__(self, reason: str | None = None) -> None:
        # ``reason`` is for logs/audit only, never returned to the client.
        self.reason = reason or self.code
        super().__init__(self.reason)


class InvalidRequestError(AppError):
    code = "invalid_request"
    http_status = 400
    public_message = "Invalid request"


class AuthenticationFailedError(AppError):
    code = "authentication_failed"
    http_status = 401
    public_message = "Authentication required"


class AccessDeniedError(AppError):
    code = "access_denied"
    http_status = 403
    public_message = "Access denied"


class ToolNotAllowedError(AppError):
    code = "tool_not_allowed"
    http_status = 403
    public_message = "Access denied"


class InvalidToolArgumentsError(AppError):
    code = "invalid_tool_arguments"
    http_status = 422
    public_message = "Invalid tool arguments"


class BudgetExceededError(AppError):
    code = "budget_exceeded"
    http_status = 429
    public_message = "Request budget exceeded"


class SecurityViolationError(AppError):
    """A guardrail rejected content produced by a dependency (e.g. LLM output)."""

    code = "invalid_dependency_response"
    http_status = 502
    public_message = "Invalid response from upstream dependency"


class DependencyError(AppError):
    """Failure of an external dependency (MCP, LLM, permissions service)."""

    retryable = False

    def __init__(self, reason: str | None = None, *, retryable: bool | None = None,
                 status_code: int | None = None) -> None:
        super().__init__(reason)
        if retryable is not None:
            self.retryable = retryable
        self.status_code = status_code


class InvalidDependencyResponseError(DependencyError):
    code = "invalid_dependency_response"
    http_status = 502
    public_message = "Invalid response from upstream dependency"


class DependencyUnavailableError(DependencyError):
    code = "dependency_unavailable"
    http_status = 503
    public_message = "Dependency temporarily unavailable"
    retryable = True


class RateLimitedError(DependencyUnavailableError):
    code = "rate_limited"
    http_status = 429
    public_message = "Rate limited, try again later"


class DependencyTimeoutError(DependencyError):
    code = "dependency_timeout"
    http_status = 504
    public_message = "Dependency timeout"
    retryable = True


def dependency_error_from_status(status_code: int, reason: str) -> DependencyError:
    """Map an upstream HTTP status to a typed error with the right retry semantics.

    Retry only: 408, 429, 5xx. Never retry 400/401/403 or validation failures.
    """
    if status_code == 429:
        return RateLimitedError(reason, status_code=status_code)
    if status_code == 408:
        return DependencyTimeoutError(reason, status_code=status_code)
    if status_code >= 500:
        return DependencyUnavailableError(reason, status_code=status_code)
    return InvalidDependencyResponseError(reason, retryable=False, status_code=status_code)
