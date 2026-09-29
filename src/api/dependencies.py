"""FastAPI dependencies: container access and authenticated context."""

from typing import Annotated

from fastapi import Depends, Header, Request

from container import Container
from domain.exceptions import AppError
from domain.models.audit import AuditEvent, AuditEventType
from domain.models.identity import AuthenticatedIdentity


def get_container(request: Request) -> Container:
    return request.app.state.container


async def get_identity(
    container: Annotated[Container, Depends(get_container)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedIdentity:
    with container.telemetry.span("auth.validate"):
        try:
            identity = await container.auth.authenticate(authorization)
        except AppError as exc:
            container.audit.record(AuditEvent(type=AuditEventType.AUTH_FAILED,
                                              details={"reason": exc.reason}))
            raise
    container.audit.record(AuditEvent(type=AuditEventType.AUTH_SUCCESS,
                                      employee_id=identity.employee_id,
                                      details={"method": identity.auth_method}))
    return identity
