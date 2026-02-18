import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
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

# ------------------------------------------------------------------
# Lifecycle (Lifespan) Events - The New Way
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown logic."""
    # Startup logic: Start the closed-loop background processor
    print("Starting SmartOps Orchestrator lifespan...")
    await closed_loop_manager.start()
    
    yield  # The app is now running and receiving requests
    
    # Shutdown logic (optional: add cleanup here)
    print("Shutting down SmartOps Orchestrator...")

# ------------------------------------------------------------------
# App Initialization
# ------------------------------------------------------------------
app = FastAPI(
    title="SmartOps Orchestrator",
    description="Executes AI + policy-driven Kubernetes actions",
    version="0.1.0",
    lifespan=lifespan  # Register the lifespan handler here
)

# ------------------------------------------------------------------
# Instrumentation & Routers
# ------------------------------------------------------------------
setup_otel(app)
Instrumentator().instrument(app)
app.include_router(metrics_router)

# Business Routers
app.include_router(orchestrator_router, prefix="/v1")
app.include_router(k8s_router, prefix="/v1")
app.include_router(verification_router, prefix="/v1")
app.include_router(signals_router, prefix="/v1")

@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": "orchestrator"}

# ------------------------------------------------------------------
# Uvicorn Runner - This allows 'python -m apps.orchestrator.app' to work
# ------------------------------------------------------------------
if __name__ == "__main__":
    # Using the string import 'apps.orchestrator.app:app' is better for Windows reload support
    uvicorn.run("apps.orchestrator.app:app", host="0.0.0.0", port=8000, reload=True)