"""Application error types and the single place an error body is built.

Every error response uses the RFC 9457 Problem Details shape. Handlers never
construct error bodies themselves, so the envelope is identical everywhere and
no route can leak an internal message or stack trace while another does not.
"""

from __future__ import annotations

from typing import Any


class AvocadoError(Exception):
    """Base for every error this application raises deliberately.

    `detail` is safe to show a client. Anything unsafe belongs in the log, not
    in this field.
    """

    status_code: int = 500
    title: str = "Internal Server Error"
    error_type: str = "about:blank"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        self.detail = detail or self.title
        self.extra = extra
        super().__init__(self.detail)


class NotFoundError(AvocadoError):
    status_code = 404
    title = "Not Found"
    error_type = "https://avocado.dev/errors/not-found"


class ConflictError(AvocadoError):
    status_code = 409
    title = "Conflict"
    error_type = "https://avocado.dev/errors/conflict"


class ValidationError(AvocadoError):
    status_code = 422
    title = "Validation Failed"
    error_type = "https://avocado.dev/errors/validation"


class AuthenticationError(AvocadoError):
    status_code = 401
    title = "Not Authenticated"
    error_type = "https://avocado.dev/errors/authentication"


class PermissionDeniedError(AvocadoError):
    status_code = 403
    title = "Permission Denied"
    error_type = "https://avocado.dev/errors/permission-denied"


class RateLimitedError(AvocadoError):
    status_code = 429
    title = "Too Many Requests"
    error_type = "https://avocado.dev/errors/rate-limited"


class UnsupportedMediaTypeError(AvocadoError):
    status_code = 415
    title = "Unsupported Media Type"
    error_type = "https://avocado.dev/errors/unsupported-media-type"


class PayloadTooLargeError(AvocadoError):
    status_code = 413
    title = "Payload Too Large"
    error_type = "https://avocado.dev/errors/payload-too-large"


class ProviderError(AvocadoError):
    """An external dependency (LLM, storage, STT) failed."""

    status_code = 502
    title = "Upstream Provider Error"
    error_type = "https://avocado.dev/errors/provider"


class ProviderCredentialError(ProviderError):
    """A provider rejected the credential itself, or the account cannot pay.

    Separate from `ProviderError` because retrying cannot fix it: a revoked key
    or an exhausted quota keeps failing until a human changes something. That
    distinction is what lets the registry stop offering a provider that will
    only produce errors, without a transient rate limit taking it down.
    """

    title = "Provider Credential Rejected"


class BudgetExceededError(AvocadoError):
    """The organization has spent its monthly ceiling.

    402 rather than 429: this is not a rate the caller can wait out within the
    month, it is a limit someone has to raise.
    """

    status_code = 402
    title = "Monthly Budget Exceeded"
    error_type = "https://avocado.dev/errors/budget-exceeded"


class SandboxError(AvocadoError):
    """Analysis code could not be executed safely, or failed while executing."""

    status_code = 422
    title = "Analysis Execution Failed"
    error_type = "https://avocado.dev/errors/sandbox"


class SandboxUnavailableError(AvocadoError):
    """No sandbox that satisfies the isolation guarantees is available.

    Raised instead of silently running generated code with weaker isolation.
    """

    status_code = 503
    title = "Analysis Sandbox Unavailable"
    error_type = "https://avocado.dev/errors/sandbox-unavailable"
