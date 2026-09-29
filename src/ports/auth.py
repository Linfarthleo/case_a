from typing import Protocol

from domain.models.identity import AuthenticatedIdentity


class AuthPort(Protocol):
    """Validates credentials. A JWT/OIDC adapter can replace the mock one."""

    async def authenticate(self, authorization: str | None) -> AuthenticatedIdentity:
        """Raise ``AuthenticationFailedError`` when credentials are missing/invalid."""
        ...
