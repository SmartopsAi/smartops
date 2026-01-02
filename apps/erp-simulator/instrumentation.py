"""
OpenTelemetry instrumentation setup for SmartOps ERP Simulator.

Features:
- OTLP gRPC exporter (reads OTEL_* env vars)
- FastAPI instrumentation
- Requests instrumentation
- SmartOps resource attributes
- Batch span processor wiring
"""

import logging
import os

from fastapi import FastAPI

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

logger = logging.getLogger("erp-simulator.instrumentation")


def configure_otel(app: FastAPI, service_name: str, environment: str) -> None:
    """
    Configure OpenTelemetry tracing for the ERP Simulator.

    Uses env vars injected by Kubernetes:
    - OTEL_EXPORTER_OTLP_ENDPOINT
    - OTEL_EXPORTER_OTLP_PROTOCOL
    - OTEL_SERVICE_NAME
    - OTEL_RESOURCE_ATTRIBUTES
    """

    # ------------------------------------------------------------------
    # 1. Read OTLP endpoint (from env)
    # ------------------------------------------------------------------
    raw_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://smartops-otelcol:4317")

    # OTLP gRPC exporter expects host:port (no http:// or https://)
    clean_endpoint = raw_endpoint.replace("http://", "").replace("https://", "")

    logger.info(f"[OTEL] Configuring OTLP gRPC exporter → {clean_endpoint}")

    # ------------------------------------------------------------------
    # 2. Resource attributes
    # ------------------------------------------------------------------
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "smartops",
            "deployment.environment": environment,
            "service.version": "0.1.0",
        }
    )

    # ------------------------------------------------------------------
    # 3. Tracer provider
    # ------------------------------------------------------------------
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # ------------------------------------------------------------------
    # 4. OTLP gRPC exporter + span processor
    # ------------------------------------------------------------------
    span_exporter = OTLPSpanExporter(
        endpoint=clean_endpoint,
        insecure=True,
    )

    span_processor = BatchSpanProcessor(span_exporter)
    provider.add_span_processor(span_processor)

    # ------------------------------------------------------------------
    # 5. Instrument FastAPI + outbound HTTP
    # ------------------------------------------------------------------
    FastAPIInstrumentor().instrument_app(app)
    RequestsInstrumentor().instrument()

    logger.info("[OTEL] OpenTelemetry tracing initialized for ERP Simulator")
