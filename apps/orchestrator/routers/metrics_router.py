from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter(tags=["metrics"])

@router.get("/metrics")
def prometheus_metrics():
    """
    Expose Prometheus metrics for scraping.
    """
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
