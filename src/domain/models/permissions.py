from pydantic import BaseModel, ConfigDict


class EmployeePermissions(BaseModel):
    """Permissions returned by the (trusted) permissions service."""

    model_config = ConfigDict(frozen=True)

    employee_id: str
    role: str
    area: str
    allowed_classifications: tuple[str, ...]
    allowed_tools: tuple[str, ...]


class AccessScope(BaseModel):
    """Effective, server-computed scope for one request.

    Every security filter (retrieval filters, tool allowlist, post-filter) is
    derived from this object and nothing else.
    """

    model_config = ConfigDict(frozen=True)

    employee_id: str
    role: str
    area: str
    allowed_classifications: tuple[str, ...]
    allowed_tools: tuple[str, ...]


class ClaimedContext(BaseModel):
    """Values the client *claims* in the request body. Never trusted, only compared."""

    model_config = ConfigDict(frozen=True)

    employee_id: str
    role: str
    area: str
