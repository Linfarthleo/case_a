"""Secure agentic RAG over internal documents.

Flow:
  query -> LLM (plan, allowed tools only) -> ToolPolicy -> ArgumentPolicy -> MCP
  -> post-filter (metadata) -> injection guardrail -> LLM (answer, NO tools)
  -> output guardrail

Design choice: there is a single planning round, and the answer call gets no
tools. Retrieved documents therefore can never trigger a tool call.
"""

import logging

from application.agents.base import AgentContext, AgentRequest
from application.llm_gateway import LLMGateway
from application.prompt_builder import PromptBuilder
from domain.exceptions import AppError, InvalidDependencyResponseError
from domain.models.audit import AuditEvent, AuditEventType
from domain.models.document import AgentResponse, Document, GuardedDocument
from domain.models.permissions import AccessScope
from domain.models.tool import ToolCall
from domain.policies.access_policy import AccessPolicy
from domain.policies.tool_policy import ArgumentPolicy, ToolPolicy
from ports.audit import AuditPort
from ports.guardrail import GuardrailPort
from ports.telemetry import TelemetryPort
from security.output_guardrail import OutputGuardrail
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class DocumentRagAgent:
    def __init__(
        self,
        llm: LLMGateway,
        registry: ToolRegistry,
        tool_policy: ToolPolicy,
        argument_policy: ArgumentPolicy,
        access_policy: AccessPolicy,
        guardrail: GuardrailPort,
        output_guardrail: OutputGuardrail,
        prompt_builder: PromptBuilder,
        audit: AuditPort,
        telemetry: TelemetryPort,
        insufficient_info_answer: str,
        log_document_content: bool = False,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._tool_policy = tool_policy
        self._argument_policy = argument_policy
        self._access_policy = access_policy
        self._guardrail = guardrail
        self._output_guardrail = output_guardrail
        self._prompts = prompt_builder
        self._audit = audit
        self._telemetry = telemetry
        self._insufficient = insufficient_info_answer
        self._log_document_content = log_document_content

    async def execute(self, request: AgentRequest, context: AgentContext) -> AgentResponse:
        scope = context.access_scope

        with self._telemetry.span("llm.plan"):
            tools = [d.llm_schema() for d in self._registry.definitions_for(scope)]
            plan = await self._llm.generate(
                self._prompts.planning_messages(request.query), context.budget, tools=tools or None
            )

        retrieved: list[Document] = []
        for call in plan.tool_calls:
            retrieved.extend(await self._execute_tool(call, request.query, context))

        authorized = self._post_filter(retrieved, scope)
        with self._telemetry.span("guardrail.documents"):
            guarded = [self._guard(doc, scope) for doc in authorized]

        if not guarded:
            # No authorized evidence: do not spend tokens, do not let the model improvise.
            return AgentResponse(answer=self._insufficient)

        with self._telemetry.span("llm.generate_answer"):
            answer = await self._llm.generate(
                self._prompts.answer_messages(request.query, guarded), context.budget, tools=None
            )
        if answer.tool_calls:
            # The answer step has no tools; a tool call here is ignored and recorded.
            self._telemetry.increment("tool_calls_denied_total", reason="tool_call_in_answer_step")

        with self._telemetry.span("guardrail.output"):
            try:
                citations = self._output_guardrail.validate(
                    answer.content, [g.document for g in guarded]
                )
            except AppError as exc:
                self._audit_event(AuditEventType.OUTPUT_REJECTED, scope, reason=exc.reason)
                raise

        sanitized = sum(1 for g in guarded if g.sanitized)
        return AgentResponse(
            answer=answer.content,
            citations=citations,
            untrusted_content_detected=sanitized > 0,
            sanitized_documents=sanitized,
        )

    # ------------------------------------------------------------------ tools
    async def _execute_tool(
        self, call: ToolCall, query: str, context: AgentContext
    ) -> list[Document]:
        scope = context.access_scope
        registered = self._registry.get(call.name)

        with self._telemetry.span("tool.authorize", tool=call.name):
            self._telemetry.increment("tool_calls_total", tool=call.name)
            context.budget.ensure_tool_call()
            try:
                definition = self._tool_policy.authorize(
                    call, registered.definition if registered else None, scope
                )
            except AppError as exc:
                self._telemetry.increment("tool_calls_denied_total", reason=exc.reason)
                self._audit_event(AuditEventType.TOOL_DENIED, scope, tool=call.name,
                                  reason=exc.reason)
                raise  # security violation: never retried, never executed
            assert registered is not None and registered.handler is not None

            safe_args, overridden = self._argument_policy.enforce(
                definition, call.arguments, registered.server_arguments(scope, query)
            )
            if overridden:
                self._audit_event(AuditEventType.TOOL_ARGUMENTS_OVERRIDDEN, scope,
                                  tool=call.name, fields=overridden)
            self._audit_event(AuditEventType.TOOL_ALLOWED, scope, tool=call.name)

        context.budget.record_tool_call()
        result = await registered.handler(safe_args)
        if result.tool_name != call.name:
            raise InvalidDependencyResponseError("tool_result_mismatch")
        return list(result.documents)

    # ---------------------------------------------------------- post-retrieval
    def _post_filter(self, documents: list[Document], scope: AccessScope) -> list[Document]:
        """Defense in depth: re-validate metadata even though MCP pre-filtered."""
        accepted: dict[str, Document] = {}
        with self._telemetry.span("metadata.validate"):
            for doc in documents:
                reason = self._access_policy.document_rejection_reason(doc, scope)
                if reason:
                    self._telemetry.increment("documents_rejected_by_policy", reason=reason)
                    self._audit_event(AuditEventType.DOCUMENT_REJECTED, scope,
                                      document_id=doc.id, reason=reason)
                    continue
                if doc.id not in accepted:
                    accepted[doc.id] = doc
                    self._telemetry.increment("documents_retrieved")
                    self._audit_event(AuditEventType.DOCUMENT_RETRIEVED, scope,
                                      document_id=doc.id, classification=doc.classification)
        return list(accepted.values())

    def _guard(self, doc: Document, scope: AccessScope) -> GuardedDocument:
        result = self._guardrail.inspect(doc.text)
        if result.finding.detected:
            self._telemetry.increment("prompt_injection_detected_total", guardrail=result.guardrail)
            self._telemetry.increment("documents_sanitized")
            self._audit_event(AuditEventType.PROMPT_INJECTION_DETECTED, scope,
                              document_id=doc.id, guardrail=result.guardrail,
                              score=result.finding.score,
                              patterns=list(result.finding.matched_patterns))
            self._audit_event(AuditEventType.DOCUMENT_SANITIZED, scope,
                              document_id=doc.id, action="sanitized")
            logger.warning("prompt_injection_detected", extra={
                "document_id": doc.id, "guardrail": result.guardrail, "action": "sanitized",
                **({"sanitized_text": result.safe_text} if self._log_document_content else {}),
            })
        return GuardedDocument(document=doc, safe_text=result.safe_text, finding=result.finding)

    def _audit_event(self, event_type: AuditEventType, scope: AccessScope, **details: object) -> None:
        self._audit.record(AuditEvent(type=event_type, employee_id=scope.employee_id,
                                      details=details))
