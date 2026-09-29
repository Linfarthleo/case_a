"""QueryDocumentsUseCase: identity -> permissions -> scope -> input guardrail -> agent."""

import asyncio
import logging
from dataclasses import dataclass

from application.agents.base import Agent, AgentContext, AgentRequest
from application.budget import BudgetLimits, ExecutionBudget
from core.resilience import with_timeout
from domain.exceptions import (
    AccessDeniedError,
    AppError,
    DependencyTimeoutError,
    DependencyUnavailableError,
)
from domain.models.audit import AuditEvent, AuditEventType
from domain.models.document import AgentResponse
from domain.models.identity import AuthenticatedIdentity
from domain.models.permissions import ClaimedContext, EmployeePermissions
from domain.policies.access_policy import AccessPolicy
from ports.audit import AuditPort
from ports.permissions import PermissionsPort
from ports.telemetry import TelemetryPort
from security.guardrails import InputGuardrail

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryDocumentsCommand:
    request_id: str
    identity: AuthenticatedIdentity
    claimed: ClaimedContext
    query: str


class QueryDocumentsUseCase:
    def __init__(
        self,
        permissions: PermissionsPort,
        access_policy: AccessPolicy,
        input_guardrail: InputGuardrail,
        agent: Agent,
        audit: AuditPort,
        telemetry: TelemetryPort,
        budget_limits: BudgetLimits,
        permissions_timeout_s: float,
    ) -> None:
        self._permissions = permissions
        self._access_policy = access_policy
        self._input_guardrail = input_guardrail
        self._agent = agent
        self._audit = audit
        self._telemetry = telemetry
        self._budget_limits = budget_limits
        self._permissions_timeout_s = permissions_timeout_s

    async def execute(self, command: QueryDocumentsCommand) -> AgentResponse:
        employee_id = command.identity.employee_id
        budget = ExecutionBudget(self._budget_limits)
        try:
            with self._telemetry.span("permissions.resolve"):
                permissions = await self._resolve_permissions(employee_id)

            with self._telemetry.span("access_policy.evaluate"):
                try:
                    scope = self._access_policy.resolve(
                        command.identity, permissions, command.claimed
                    )
                except AppError as exc:
                    self._record(AuditEventType.ACCESS_DENIED, employee_id, reason=exc.reason)
                    raise
                self._record(AuditEventType.ACCESS_GRANTED, employee_id, area=scope.area,
                             classifications=list(scope.allowed_classifications))

            with self._telemetry.span("guardrail.input"):
                try:
                    query = self._input_guardrail.validate(command.query)
                except AppError as exc:
                    self._record(AuditEventType.INPUT_REJECTED, employee_id, reason=exc.reason)
                    raise

            context = AgentContext(command.request_id, scope, budget)
            try:
                result = await asyncio.wait_for(
                    self._agent.execute(AgentRequest(query=query), context),
                    timeout=max(budget.remaining_s(), 0.001),
                )
            except TimeoutError as exc:
                raise DependencyTimeoutError("request_deadline_exceeded") from exc

        except AppError as exc:
            if exc.code == "budget_exceeded":
                self._telemetry.increment("budget_exceeded_total", reason=exc.reason)
            self._write_audit(AuditEventType.QUERY_FAILED, employee_id, error=exc.code,
                              reason=exc.reason)
            raise

        self._write_audit(
            AuditEventType.QUERY_COMPLETED, employee_id,
            citations=[c.document_id for c in result.citations],
            sanitized_documents=result.sanitized_documents,
            llm_calls=budget.llm_calls, tool_calls=budget.tool_calls,
            input_tokens=budget.input_tokens, output_tokens=budget.output_tokens,
            estimated_cost_usd=round(budget.cost_usd, 6),
        )
        return result

    async def _resolve_permissions(self, employee_id: str) -> EmployeePermissions:
        """Fail closed: if permissions cannot be resolved, no document is queried."""
        try:
            return await with_timeout(self._permissions.get_permissions(employee_id),
                                      self._permissions_timeout_s, "permissions_timeout")
        except AccessDeniedError as exc:
            self._record(AuditEventType.ACCESS_DENIED, employee_id, reason=exc.reason)
            raise
        except Exception as exc:
            self._record(AuditEventType.ACCESS_DENIED, employee_id,
                         reason="permissions_unavailable")
            raise DependencyUnavailableError("permissions_unavailable", retryable=False) from exc

    def _write_audit(self, event_type: AuditEventType, employee_id: str, **details: object) -> None:
        with self._telemetry.span("audit.write"):
            self._record(event_type, employee_id, **details)

    def _record(self, event_type: AuditEventType, employee_id: str, **details: object) -> None:
        self._audit.record(AuditEvent(type=event_type, employee_id=employee_id, details=details))
