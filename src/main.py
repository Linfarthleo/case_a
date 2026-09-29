"""FastAPI application factory."""

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from api.errors import register_error_handlers
from api.v1.docs import router as docs_router
from container import Container, build_container
from core.config import Settings, get_settings
from core.context import correlation_id_var, request_id_var
from observability.logging import configure_logging, current_trace_id
from observability.tracing import setup_tracing

logger = logging.getLogger(__name__)
_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    if settings.otel_enabled:
        setup_tracing(settings.app_name, settings.otel_exporter)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container or build_container(settings)
        logger.info("app_started", extra={"env": settings.app_env,
                                          "llm_provider": settings.llm_provider,
                                          "prompt_version": settings.prompt_version})
        yield

    app = FastAPI(title="Secure RAG Agent", version="1.0.0", lifespan=lifespan,
                  docs_url="/docs" if settings.app_env != "prod" else None, redoc_url=None)
    # Set eagerly as well so the app also works without lifespan (e.g. in simple test clients).
    app.state.container = container
    register_error_handlers(app)
    app.include_router(docs_router)

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        request_id = f"req-{uuid.uuid4().hex}"
        incoming = request.headers.get("x-correlation-id", "")
        correlation_id = incoming if _CORRELATION_ID.match(incoming) else request_id
        rid_token = request_id_var.set(request_id)
        cid_token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()
        metrics = getattr(request.app.state.container, "telemetry", None)
        try:
            response = await call_next(request)
        except Exception as exc:  # last resort: generic 500, no stack trace to the client
            logger.error("unexpected_error", extra={"exception_type": type(exc).__name__})
            response = JSONResponse(status_code=500, content={"error": {
                "code": "unexpected_error", "message": "Unexpected error",
                "request_id": request_id}})
        finally:
            request_id_var.reset(rid_token)
            correlation_id_var.reset(cid_token)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        if metrics:
            elapsed = (time.perf_counter() - started) * 1000
            metrics.increment("http_requests_total", method=request.method, path=path,
                              status=str(response.status_code))
            metrics.observe("http_request_duration_ms", elapsed, path=path)
            if response.status_code >= 400:
                metrics.increment("http_errors_total", path=path, status=str(response.status_code))
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = correlation_id
        trace_id = current_trace_id()
        if trace_id:
            response.headers["X-Trace-ID"] = trace_id
        return response

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready(request: Request) -> JSONResponse:
        ok = getattr(request.app.state, "container", None) is not None
        return JSONResponse(status_code=200 if ok else 503,
                            content={"status": "ready" if ok else "not_ready"})

    if settings.metrics_endpoint_enabled:
        @app.get("/metrics", tags=["observability"])
        async def metrics_snapshot(request: Request) -> dict:
            return request.app.state.container.metrics.snapshot()

    if settings.otel_enabled:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app, excluded_urls="health/.*,metrics")
        except Exception:
            logger.warning("otel_instrumentation_failed")

    return app


app = create_app()
