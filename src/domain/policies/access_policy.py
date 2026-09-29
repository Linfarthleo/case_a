"""RBAC: turns (identity, permissions, claimed body values) into an AccessScope.

Pure, deterministic code. The LLM never participates in these decisions.
"""

from domain.exceptions import AccessDeniedError
from domain.models.document import Document
from domain.models.identity import AuthenticatedIdentity
from domain.models.permissions import AccessScope, ClaimedContext, EmployeePermissions


class AccessPolicy:
    def resolve(
        self,
        identity: AuthenticatedIdentity,
        permissions: EmployeePermissions,
        claimed: ClaimedContext,
    ) -> AccessScope:
        if permissions.employee_id != identity.employee_id:
            raise AccessDeniedError("permissions_identity_mismatch")
        # The body is compared against the server truth, never used as a source.
        if claimed.employee_id != identity.employee_id:
            raise AccessDeniedError("employee_id_mismatch")
        if claimed.role != permissions.role:
            raise AccessDeniedError("role_mismatch")
        if claimed.area != permissions.area:
            raise AccessDeniedError("area_mismatch")
        if not permissions.allowed_classifications:
            raise AccessDeniedError("no_classifications")  # least privilege: nothing to read

        return AccessScope(
            employee_id=identity.employee_id,
            role=permissions.role,
            area=permissions.area,
            allowed_classifications=permissions.allowed_classifications,
            allowed_tools=permissions.allowed_tools,
        )

    @staticmethod
    def document_rejection_reason(document: Document, scope: AccessScope) -> str | None:
        """Post-retrieval check (defense in depth). Returns why a document is rejected."""
        if document.area != scope.area:
            return "area_not_authorized"
        if document.classification not in scope.allowed_classifications:
            return "classification_not_authorized"
        return None
