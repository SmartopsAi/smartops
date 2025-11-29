from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

# OTEL
from apps.orchestrator.utils.otel import setup_otel

# Routers
from apps.orchestrator.services.orchestrator_service import router as orchestrator_router
from apps.orchestrator.routers.k8s_router import router as k8s_router
from apps.orchestrator.routers.verification_router import router as verification_router
from apps.orchestrator.routers.signals_router import router as signals_router
from apps.orchestrator.services.closed_loop import closed_loop_manager

app = FastAPI(
    title="SmartOps Orchestrator",
    description="Executes policy and AI-driven actions on Kubernetes",
    version="0.1.0",
)

# OpenTelemetry setup
setup_otel(app)

# PROMETHEUS /metrics
Instrumentator().instrument(app).expose(app, include_in_schema=False, endpoint="/metrics")

# Routers
app.include_router(orchestrator_router, prefix="/v1")
app.include_router(k8s_router, prefix="/v1")
app.include_router(verification_router, prefix="/v1")
app.include_router(signals_router, prefix="/v1")

@app.on_event("startup")
async def startup_event():
    await closed_loop_manager.start()

@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": "orchestrator"}
