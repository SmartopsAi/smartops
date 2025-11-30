from fastapi import FastAPI
# We keep the import but no longer use expose() for /metrics
from prometheus_fastapi_instrumentator import Instrumentator

# OTEL
from utils.otel import setup_otel

# Routers
from services.orchestrator_service import router as orchestrator_router
from routers.k8s_router import router as k8s_router
from routers.verification_router import router as verification_router
from routers.signals_router import router as signals_router
from routers.metrics_router import router as metrics_router  # ✅ NEW

from services.closed_loop import closed_loop_manager


app = FastAPI(
    title="SmartOps Orchestrator",
    description="Executes policy and AI-driven actions on Kubernetes",
    version="0.1.0",
)

# OpenTelemetry setup
setup_otel(app)

# ------------------------------------------------------------------
# Prometheus metrics
# ------------------------------------------------------------------
# We still instrument the app (for request metrics, etc.),
# but we DO NOT call `.expose()` here.
# That avoids any confusion about which /metrics is active.
Instrumentator().instrument(app)

# Explicit metrics router -> /metrics
app.include_router(metrics_router)  # ✅ /metrics now handled by metrics_router

# ------------------------------------------------------------------
# Business routers
# ------------------------------------------------------------------
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
