# apps/orchestrator/app.py

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

# OTEL setup
from apps.orchestrator.utils.otel import setup_otel

# Routers (absolute imports)
from apps.orchestrator.services.orchestrator_service import router as orchestrator_router
from apps.orchestrator.routers.k8s_router import router as k8s_router
from apps.orchestrator.routers.verification_router import router as verification_router
from apps.orchestrator.routers.signals_router import router as signals_router
from apps.orchestrator.routers.metrics_router import router as metrics_router

# Closed-loop manager
from apps.orchestrator.services.closed_loop import closed_loop_manager


app = FastAPI(
    title="SmartOps Orchestrator",
    description="Executes AI + policy-driven Kubernetes actions",
    version="0.1.0",
)

# ------------------------------------------------------------------
# OpenTelemetry
# ------------------------------------------------------------------
setup_otel(app)

# ------------------------------------------------------------------
# Prometheus Metrics
# ------------------------------------------------------------------
# Instrument HTTP request metrics, latency, etc.
Instrumentator().instrument(app)

# Expose our explicit /metrics endpoint
app.include_router(metrics_router)


# ------------------------------------------------------------------
# Business Routers
# ------------------------------------------------------------------
app.include_router(orchestrator_router, prefix="/v1")
app.include_router(k8s_router, prefix="/v1")
app.include_router(verification_router, prefix="/v1")
app.include_router(signals_router, prefix="/v1")


# ------------------------------------------------------------------
# Lifecycle Events
# ------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """Start the closed-loop background processor."""
    await closed_loop_manager.start()


@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": "orchestrator"}
