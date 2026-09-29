"""POST /api/v1/docs/query — thin controller: DTO in, use case, DTO out."""

from typing import Annotated

from fastapi import APIRouter, Depends

from api.dependencies import get_container, get_identity
from api.v1.schemas import CitationDTO, ErrorResponse, QueryRequest, QueryResponse, SecurityDTO
from application.use_cases.query_documents import QueryDocumentsCommand
from container import Container
from core.context import request_id_var
from domain.models.identity import AuthenticatedIdentity
from domain.models.permissions import ClaimedContext

router = APIRouter(prefix="/api/v1/docs", tags=["docs"])

_ERRORS = {code: {"model": ErrorResponse} for code in (400, 401, 403, 422, 429, 502, 503, 504)}


@router.post("/query", response_model=QueryResponse, responses=_ERRORS)
async def query_documents(
    body: QueryRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_identity)],
    container: Annotated[Container, Depends(get_container)],
) -> QueryResponse:
    request_id = request_id_var.get() or "unknown"
    result = await container.use_case.execute(
        QueryDocumentsCommand(
            request_id=request_id,
            identity=identity,
            claimed=ClaimedContext(employee_id=body.employee_id, role=body.role, area=body.area),
            query=body.query,
        )
    )
    return QueryResponse(
        request_id=request_id,
        answer=result.answer,
        citations=[CitationDTO(document_id=c.document_id, title=c.title) for c in result.citations],
        security=SecurityDTO(
            untrusted_content_detected=result.untrusted_content_detected,
            sanitized_documents=result.sanitized_documents,
        ),
    )
