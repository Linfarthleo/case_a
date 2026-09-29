from pydantic import BaseModel, ConfigDict


class AuthenticatedIdentity(BaseModel):
    """Identity proven by the authentication provider. Source of truth for *who*."""

    model_config = ConfigDict(frozen=True)

    employee_id: str
    auth_method: str
