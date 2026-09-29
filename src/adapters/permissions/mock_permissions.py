"""In-memory stand-in for the corporate permissions service (HR / IAM)."""

from domain.exceptions import AccessDeniedError
from domain.models.permissions import EmployeePermissions

_EMPLOYEES: dict[str, EmployeePermissions] = {
    p.employee_id: p
    for p in (
        EmployeePermissions(
            employee_id="E001", role="comercial", area="creditos",
            allowed_classifications=("public", "internal"),
            allowed_tools=("mcp_search_documents",),
        ),
        EmployeePermissions(
            employee_id="E002", role="analista", area="talento",
            allowed_classifications=("public", "internal"),
            allowed_tools=("mcp_search_documents",),
        ),
        EmployeePermissions(
            employee_id="E003", role="gerente", area="creditos",
            allowed_classifications=("public", "internal", "confidential"),
            allowed_tools=("mcp_search_documents",),
        ),
        EmployeePermissions(  # authenticated but with no tools: can never retrieve
            employee_id="E004", role="practicante", area="creditos",
            allowed_classifications=("public",),
            allowed_tools=(),
        ),
    )
}


class MockPermissionsAdapter:
    async def get_permissions(self, employee_id: str) -> EmployeePermissions:
        permissions = _EMPLOYEES.get(employee_id)
        if permissions is None:
            raise AccessDeniedError("unknown_employee")
        return permissions
