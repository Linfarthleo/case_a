"""Composition root: the only place that knows concrete adapters.

Swapping an adapter (real MCP, OIDC, another LLM provider) happens here, not
in the use case or the agent. Tests inject fakes through the keyword overrides.
"""

from dataclasses import dataclass

from adapters.audit.logging_audit import LoggingAuditAdapter
from adapters.auth.mock_auth import MockAuthAdapter
from adapters.llm.provider import build_llm_provider
from adapters.mcp.resilient_mcp import ResilientMcpClient
from adapters.mcp.simulated_mcp import SimulatedMcpAdapter
from adapters.permissions.mock_permissions import MockPermissionsAdapter
from application.agents.base import AgentRegistry
from application.agents.document_rag_agent import DocumentRagAgent
from application.budget import BudgetLimits
from application.llm_gateway import LLMGateway
from application.prompt_builder import PromptBuilder
from application.use_cases.query_documents import QueryDocumentsUseCase
from core.config import Settings
from core.prompts import load_prompt
from core.resilience import CircuitBreaker
from domain.policies.access_policy import AccessPolicy
from domain.policies.tool_policy import ArgumentPolicy, ToolPolicy
from observability.metrics import MetricsRegistry
from observability.tracing import Telemetry
from ports.audit import AuditPort
from ports.auth import AuthPort
from ports.guardrail import GuardrailPort
from ports.llm import LLMPort
from ports.mcp import McpClientPort
from ports.permissions import PermissionsPort
from security.document_sanitizer import DocumentSanitizer
from security.guardrails import InputGuardrail, RuleBasedGuardrail
from security.injection_detector import InjectionDetector
from security.output_guardrail import OutputGuardrail
from tools.registry import build_tool_registry

DOCS_RAG_AGENT = "docs_rag"


@dataclass
class Container:
    settings: Settings
    telemetry: Telemetry
    metrics: MetricsRegistry
    audit: AuditPort
    auth: AuthPort
    use_case: QueryDocumentsUseCase
    agents: AgentRegistry


def _breaker(name: str, s: Settings) -> CircuitBreaker:
    return CircuitBreaker(name, s.circuit_breaker_failure_threshold,
                          s.circuit_breaker_reset_timeout_s)


def _guardrail(s: Settings) -> GuardrailPort:
    # GUARDRAIL_MODE=rules is the MVP. A model-based classifier would be wrapped as
    # FallbackGuardrail(ModelGuardrail(...), RuleBasedGuardrail(...)).
    return RuleBasedGuardrail(InjectionDetector(s.injection_threshold), DocumentSanitizer())


def build_container(
    settings: Settings,
    *,
    auth: AuthPort | None = None,
    permissions: PermissionsPort | None = None,
    mcp: McpClientPort | None = None,
    llm_provider: LLMPort | None = None,
    audit: AuditPort | None = None,
    metrics: MetricsRegistry | None = None,
) -> Container:
    s = settings
    metrics = metrics or MetricsRegistry(otel_enabled=s.otel_enabled)
    telemetry = Telemetry(metrics, enabled=s.otel_enabled)
    audit = audit or LoggingAuditAdapter()
    base_delay, max_delay = s.retry_base_delay_ms / 1000, s.retry_max_delay_ms / 1000

    mcp_client = ResilientMcpClient(
        mcp or SimulatedMcpAdapter(top_k=s.mcp_top_k), telemetry, _breaker("mcp", s),
        timeout_s=s.mcp_timeout_ms / 1000, max_retries=s.mcp_max_retries,
        base_delay_s=base_delay, max_delay_s=max_delay,
    )
    llm = LLMGateway(llm_provider or build_llm_provider(s), s, telemetry, _breaker("llm", s))

    system_prompt = load_prompt("docs_rag", s.prompt_version,
                                {"INSUFFICIENT_INFO_ANSWER": s.insufficient_info_answer})
    guardrail = _guardrail(s)
    access_policy = AccessPolicy()

    agents = AgentRegistry()
    agents.register(DOCS_RAG_AGENT, DocumentRagAgent(
        llm=llm,
        registry=build_tool_registry(mcp_client),
        tool_policy=ToolPolicy(),
        argument_policy=ArgumentPolicy(),
        access_policy=access_policy,
        guardrail=guardrail,
        output_guardrail=OutputGuardrail(system_prompt, s.max_answer_chars,
                                         s.output_require_citations, s.insufficient_info_answer),
        prompt_builder=PromptBuilder(system_prompt),
        audit=audit,
        telemetry=telemetry,
        insufficient_info_answer=s.insufficient_info_answer,
        log_document_content=s.log_document_content,
    ))

    use_case = QueryDocumentsUseCase(
        permissions=permissions or MockPermissionsAdapter(),
        access_policy=access_policy,
        input_guardrail=InputGuardrail(guardrail, s.max_query_chars),
        agent=agents.get(DOCS_RAG_AGENT),
        audit=audit,
        telemetry=telemetry,
        budget_limits=BudgetLimits.from_settings(s),
        permissions_timeout_s=s.permissions_timeout_ms / 1000,
    )
    return Container(s, telemetry, metrics, audit, auth or MockAuthAdapter(), use_case, agents)
