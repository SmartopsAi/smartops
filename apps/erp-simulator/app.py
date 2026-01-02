"""
ERP Simulator service for SmartOps.

Now includes:
- FastAPI API
- CPU load simulation
- Synthetic anomaly modes (memory leak, CPU spike, latency jitter, error burst)
- Chaos control endpoints
- Background worker
- Prometheus metrics
- OpenTelemetry tracing
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from opentelemetry import trace

# -----------------------------
# Prometheus Metrics
# -----------------------------
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# Create a custom registry to avoid duplication issues
PROM_REGISTRY = CollectorRegistry()

REQUEST_COUNTER = Counter(
    "erp_simulator_requests_total",
    "Total number of requests to ERP Simulator",
    ["method", "endpoint"],
    registry=PROM_REGISTRY,
)

LOAD_DURATION = Histogram(
    "erp_simulator_load_duration_seconds",
    "Duration of load simulations",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30],
    registry=PROM_REGISTRY,
)

ERROR_COUNTER = Counter(
    "erp_simulator_errors_total",
    "Total number of simulated errors",
    ["endpoint"],
    registry=PROM_REGISTRY,
)

LATENCY_JITTER_HIST = Histogram(
    "erp_simulator_latency_jitter_ms",
    "Injected latency jitter in milliseconds",
    buckets=[10, 50, 100, 250, 500, 1000, 2000],
    registry=PROM_REGISTRY,
)

CPU_BURN_HIST = Histogram(
    "erp_simulator_cpu_burn_ms",
    "CPU burn duration in milliseconds",
    buckets=[10, 50, 100, 250, 500, 1000, 2000, 5000],
    registry=PROM_REGISTRY,
)

MEMORY_LEAK_BYTES = Counter(
    "erp_simulator_memory_leak_bytes_total",
    "Total bytes allocated for simulated memory leaks",
    registry=PROM_REGISTRY,
)

MODES_ENABLED_GAUGE = Gauge(
    "erp_simulator_modes_enabled",
    "Number of active anomaly modes",
    registry=PROM_REGISTRY,
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

    # Phase 3 anomaly-related config
    base_error_rate: float = float(os.getenv("SIM_BASE_ERROR_RATE", "0.05"))
    max_extra_latency_ms: int = int(os.getenv("SIM_MAX_EXTRA_LATENCY_MS", "1000"))

    memory_leak_enabled: bool = os.getenv("SIM_MEMORY_LEAK_ENABLED", "false").lower() == "true"
    cpu_spike_enabled: bool = os.getenv("SIM_CPU_SPIKE_ENABLED", "false").lower() == "true"
    latency_jitter_enabled: bool = os.getenv("SIM_LATENCY_JITTER_ENABLED", "false").lower() == "true"
    error_burst_enabled: bool = os.getenv("SIM_ERROR_BURST_ENABLED", "false").lower() == "true"


def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# ---------------------------------------------------------------------------
# Global anomaly mode state
# ---------------------------------------------------------------------------

SIM_MODES: Dict[str, bool] = {
    "memory_leak": settings.memory_leak_enabled,
    "cpu_spike": settings.cpu_spike_enabled,
    "latency_jitter": settings.latency_jitter_enabled,
    "error_burst": settings.error_burst_enabled,
}

MEMORY_LEAK_BUCKET: list[bytes] = []

_bg_task: Optional[asyncio.Task] = None

# ---------------------------------------------------------------------------
# Logging & Tracing
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(settings.app_name)
tracer = trace.get_tracer(__name__)


def _update_modes_gauge() -> None:
    active = sum(1 for v in SIM_MODES.values() if v)
    MODES_ENABLED_GAUGE.set(active)
    logger.info("Updated modes gauge, active=%d, SIM_MODES=%s", active, SIM_MODES)


def _cpu_burn(duration_seconds: float) -> float:
    """
    Busy-loop CPU for approximately duration_seconds.
    Returns the actual elapsed time.
    """
    start = time.time()
    x = 0
    while (time.time() - start) < duration_seconds:
        x += 1  # simple CPU work
    end = time.time()
    return end - start


async def _background_worker() -> None:
    """
    Background task that periodically applies anomaly patterns
    (small CPU spikes, memory allocations) when modes are enabled.
    """
    while True:
        try:
            with tracer.start_as_current_span("erp_simulator.background_worker") as span:
                span.set_attribute("sim.mode.memory_leak", SIM_MODES["memory_leak"])
                span.set_attribute("sim.mode.cpu_spike", SIM_MODES["cpu_spike"])

                # Small periodic CPU burn
                if SIM_MODES["cpu_spike"]:
                    with CPU_BURN_HIST.time():
                        elapsed = _cpu_burn(0.1)
                        span.set_attribute("sim.cpu_burn_ms", elapsed * 1000.0)

                # Small periodic memory growth
                if SIM_MODES["memory_leak"]:
                    leak_bytes = random.randint(50_000, 200_000)
                    MEMORY_LEAK_BUCKET.append(b"x" * leak_bytes)
                    MEMORY_LEAK_BYTES.inc(leak_bytes)
                    span.set_attribute("sim.memory_allocated_bytes", leak_bytes)

            await asyncio.sleep(5.0)
        except Exception:
            logger.exception("Background worker encountered an error")
            await asyncio.sleep(5.0)


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SmartOps ERP Simulator",
    description="Simulated ERP workload service for SmartOps testing.",
    version="0.2.0",
)

# OTEL auto instrumentation
configure_otel(
    app,
    service_name=settings.app_name,
    environment=settings.environment,
)


@app.on_event("startup")
async def on_startup() -> None:
    global _bg_task
    logger.info("Starting ERP Simulator with SIM_MODES=%s", SIM_MODES)
    _update_modes_gauge()
    if _bg_task is None:
        _bg_task = asyncio.create_task(_background_worker())


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
        description="Base duration of CPU load simulation.",
    )
    target: Optional[str] = "cpu"


class LoadSimulationResponse(BaseModel):
    message: str
    duration_seconds: float
    target: str


class ChaosModeResponse(BaseModel):
    modes: Dict[str, bool]


class ChaosToggleResponse(BaseModel):
    mode: str
    enabled: bool


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

@app.get("/test-trace", tags=["debug"])
def test_trace() -> dict:
    # Manual span to prove tracing works
    with tracer.start_as_current_span("manual-test-span"):
        logger.info("Inside /test-trace handler")
        time.sleep(0.1)

    return {
        "status": "ok",
        "message": "trace span generated from /test-trace",
        "service": settings.app_name,
        "env": settings.environment,
    }


@app.get("/healthz", response_model=HealthResponse, tags=["internal"])
def healthz() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        env=settings.environment,
    )


@app.post("/simulate/load", response_model=LoadSimulationResponse, tags=["simulation"])
def simulate_load(payload: LoadSimulationRequest) -> LoadSimulationResponse:
    """
    Simulate a request that can exhibit multiple anomaly modes:

    - CPU spike       (extra CPU burn)
    - Latency jitter  (random sleep)
    - Memory leak     (allocate bytes into a global list)
    - Error burst     (probabilistic HTTP 500)
    """
    if payload.duration_seconds < 0:
        raise HTTPException(400, "duration_seconds must be positive")

    with tracer.start_as_current_span("erp_simulator.simulate_load") as span, LOAD_DURATION.time():
        span.set_attribute("sim.mode.memory_leak", SIM_MODES["memory_leak"])
        span.set_attribute("sim.mode.cpu_spike", SIM_MODES["cpu_spike"])
        span.set_attribute("sim.mode.latency_jitter", SIM_MODES["latency_jitter"])
        span.set_attribute("sim.mode.error_burst", SIM_MODES["error_burst"])

        # 1) Latency jitter
        jitter_ms = 0.0
        if SIM_MODES["latency_jitter"]:
            jitter_ms = random.uniform(0, settings.max_extra_latency_ms)
            LATENCY_JITTER_HIST.observe(jitter_ms)
            span.set_attribute("sim.extra_delay_ms", jitter_ms)
            time.sleep(jitter_ms / 1000.0)

        # 2) Memory leak
        if SIM_MODES["memory_leak"]:
            leak_bytes = random.randint(100_000, 1_000_000)
            MEMORY_LEAK_BUCKET.append(b"x" * leak_bytes)
            MEMORY_LEAK_BYTES.inc(leak_bytes)
            span.set_attribute("sim.memory_allocated_bytes", leak_bytes)

        # 3) CPU load (base + optional spike)
        cpu_duration = payload.duration_seconds
        if SIM_MODES["cpu_spike"]:
            cpu_duration += 0.5  # simple extra burn for spike

        with CPU_BURN_HIST.time():
            elapsed = _cpu_burn(cpu_duration)
            span.set_attribute("sim.cpu_burn_ms", elapsed * 1000.0)

        # 4) Error burst
        error_rate = settings.base_error_rate
        if SIM_MODES["error_burst"]:
            error_rate = max(error_rate, 0.4)  # bump to at least 40%

        if random.random() < error_rate:
            ERROR_COUNTER.labels(endpoint="/simulate/load").inc()
            span.set_attribute("sim.error_injected", True)
            logger.warning("Simulated error burst triggered")
            raise HTTPException(status_code=500, detail="Simulated error burst")

        # Normal success
        span.set_attribute("sim.error_injected", False)

    return LoadSimulationResponse(
        message="Load simulation completed",
        duration_seconds=payload.duration_seconds,
        target=payload.target or "cpu",
    )


# ---------------------------------------------------------------------------
# Chaos control endpoints
# ---------------------------------------------------------------------------

@app.get("/chaos/modes", response_model=ChaosModeResponse, tags=["chaos"])
def get_modes() -> ChaosModeResponse:
    """
    Return the current anomaly mode configuration.
    """
    return ChaosModeResponse(modes=SIM_MODES.copy())


def _set_mode(mode: str, enabled: bool) -> ChaosToggleResponse:
    if mode not in SIM_MODES:
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")
    SIM_MODES[mode] = enabled
    _update_modes_gauge()
    logger.info("Chaos mode %s set to %s", mode, enabled)
    return ChaosToggleResponse(mode=mode, enabled=enabled)


@app.post("/chaos/memory-leak/enable", response_model=ChaosToggleResponse, tags=["chaos"])
def enable_memory_leak() -> ChaosToggleResponse:
    return _set_mode("memory_leak", True)


@app.post("/chaos/memory-leak/disable", response_model=ChaosToggleResponse, tags=["chaos"])
def disable_memory_leak() -> ChaosToggleResponse:
    return _set_mode("memory_leak", False)


@app.post("/chaos/cpu-spike/enable", response_model=ChaosToggleResponse, tags=["chaos"])
def enable_cpu_spike() -> ChaosToggleResponse:
    return _set_mode("cpu_spike", True)


@app.post("/chaos/cpu-spike/disable", response_model=ChaosToggleResponse, tags=["chaos"])
def disable_cpu_spike() -> ChaosToggleResponse:
    return _set_mode("cpu_spike", False)


@app.post("/chaos/latency-jitter/enable", response_model=ChaosToggleResponse, tags=["chaos"])
def enable_latency_jitter() -> ChaosToggleResponse:
    return _set_mode("latency_jitter", True)


@app.post("/chaos/latency-jitter/disable", response_model=ChaosToggleResponse, tags=["chaos"])
def disable_latency_jitter() -> ChaosToggleResponse:
    return _set_mode("latency_jitter", False)


@app.post("/chaos/error-burst/enable", response_model=ChaosToggleResponse, tags=["chaos"])
def enable_error_burst() -> ChaosToggleResponse:
    return _set_mode("error_burst", True)


@app.post("/chaos/error-burst/disable", response_model=ChaosToggleResponse, tags=["chaos"])
def disable_error_burst() -> ChaosToggleResponse:
    return _set_mode("error_burst", False)


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
        port=int(os.getenv("PORT", 9000)),
        reload=False,  # Disable reload to avoid double metric registration
        factory=True,
    )
