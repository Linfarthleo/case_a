from typing import Protocol

from domain.models.permissions import EmployeePermissions


class PermissionsPort(Protocol):
    """Trusted source of employee permissions (``get_employee_permissions``)."""

    async def get_permissions(self, employee_id: str) -> EmployeePermissions:
        """Raise ``AccessDeniedError`` if unknown, ``DependencyError`` if unavailable."""
        ...
