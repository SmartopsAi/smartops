"""
ERP Simulator service for SmartOps.

Now includes:
- FastAPI API
- CPU load simulation
- Health endpoint
- Prometheus metrics
- OpenTelemetry tracing
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

# -----------------------------
# Prometheus Metrics
# -----------------------------
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# Create a custom registry to avoid duplication issues
PROM_REGISTRY = CollectorRegistry()

REQUEST_COUNTER = Counter(
    "erp_simulator_requests_total",
    "Total number of requests to ERP Simulator",
    ["method", "endpoint"],
    registry=PROM_REGISTRY
)

LOAD_DURATION = Histogram(
    "erp_simulator_load_duration_seconds",
    "Duration of load simulations",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30],
    registry=PROM_REGISTRY
)


# -----------------------------
# OpenTelemetry Instrumentation
# -----------------------------
from instrumentation import configure_otel


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    app_name: str = "erp-simulator"
    environment: str = os.getenv("SMARTOPS_ENV", "dev")
    log_level: str = os.getenv("ERP_SIMULATOR_LOG_LEVEL", "INFO")
    otlp_endpoint: str = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://otelcol-opentelemetry-collector:4317",
    )


def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(settings.app_name)

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SmartOps ERP Simulator",
    description="Simulated ERP workload service for SmartOps testing.",
    version="0.1.0",
)

# OTEL auto instrumentation
configure_otel(
    app,
    service_name=settings.app_name,
    environment=settings.environment,
)


# ---------------------------------------------------------------------------
# Prometheus /metrics endpoint
# ---------------------------------------------------------------------------

@app.get("/metrics")
def metrics() -> Response:
    data = generate_latest(PROM_REGISTRY)
    return Response(data, media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    app: str
    env: str


class LoadSimulationRequest(BaseModel):
    duration_seconds: float = Field(
        0.5,
        ge=0.0,
        le=30.0,
        description="Duration of CPU load simulation.",
    )
    target: Optional[str] = "cpu"


class LoadSimulationResponse(BaseModel):
    message: str
    duration_seconds: float
    target: str


# ---------------------------------------------------------------------------
# Middleware for Prometheus metrics
# ---------------------------------------------------------------------------

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    REQUEST_COUNTER.labels(method=request.method, endpoint=request.url.path).inc()
    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthz", response_model=HealthResponse, tags=["internal"])
def healthz() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        env=settings.environment,
    )


@app.post("/simulate/load", response_model=LoadSimulationResponse, tags=["simulation"])
def simulate_load(payload: LoadSimulationRequest) -> LoadSimulationResponse:
    if payload.duration_seconds < 0:
        raise HTTPException(400, "duration_seconds must be positive")

    with LOAD_DURATION.time():  # Prometheus histogram timing
        end_time = time.time() + payload.duration_seconds
        x = 0
        while time.time() < end_time:
            x += 1

    return LoadSimulationResponse(
        message="Load simulation completed",
        duration_seconds=payload.duration_seconds,
        target=payload.target or "cpu",
    )

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:create_app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False,  # Disable reload to avoid double metric registration
        factory=True,
    )
