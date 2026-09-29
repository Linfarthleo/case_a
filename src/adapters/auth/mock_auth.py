"""Evaluation-only authentication: ``Bearer employee-E001`` -> employee E001.

A JWT/OIDC adapter implementing ``AuthPort`` can replace this without touching
the use case.
"""

import re

from domain.exceptions import AuthenticationFailedError
from domain.models.identity import AuthenticatedIdentity

_TOKEN = re.compile(r"^Bearer employee-([A-Z0-9]{1,16})$")


class MockAuthAdapter:
    async def authenticate(self, authorization: str | None) -> AuthenticatedIdentity:
        if not authorization:
            raise AuthenticationFailedError("missing_token")
        match = _TOKEN.match(authorization.strip())
        if not match:
            raise AuthenticationFailedError("invalid_token")
        return AuthenticatedIdentity(employee_id=match.group(1), auth_method="mock_bearer")
