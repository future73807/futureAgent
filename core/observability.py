"""Minimal operational telemetry with safe, structured request logs."""
from __future__ import annotations

import json
import logging
from time import perf_counter

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


logger = logging.getLogger("futureagent.operations")

HTTP_REQUESTS = Counter(
    "futureagent_http_requests_total",
    "Completed HTTP requests by method, route and status.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "futureagent_http_request_duration_seconds",
    "HTTP request duration by method and route.",
    ("method", "route"),
)
HTTP_IN_FLIGHT = Gauge(
    "futureagent_http_requests_in_flight",
    "HTTP requests currently being processed.",
)
AGENT_RUNS = Counter(
    "futureagent_agent_runs_total",
    "Task-level AI execution attempts by terminal outcome.",
    ("status",),
)
ATTACHMENT_UPLOADS = Counter(
    "futureagent_attachment_uploads_total",
    "Completed attachment uploads.",
    ("backend",),
)


def record_agent_run(status: str) -> None:
    AGENT_RUNS.labels(status=status).inc()


def record_attachment_upload(backend: str) -> None:
    ATTACHMENT_UPLOADS.labels(backend=backend).inc()


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


def install_observability(app: FastAPI) -> None:
    """Add request metrics and JSON logs without logging secrets or bodies."""

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        started = perf_counter()
        HTTP_IN_FLIGHT.inc()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = perf_counter() - started
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or request.url.path
            labels = {"method": request.method, "route": route_path}
            HTTP_REQUESTS.labels(**labels, status=str(status_code)).inc()
            HTTP_DURATION.labels(**labels).observe(elapsed)
            HTTP_IN_FLIGHT.dec()
            logger.info(
                json.dumps(
                    {
                        "event": "http.request.completed",
                        "method": request.method,
                        "route": route_path,
                        "status": status_code,
                        "duration_ms": round(elapsed * 1000, 2),
                        "request_id": request.headers.get("x-request-id", ""),
                    },
                    ensure_ascii=False,
                )
            )
