"""
OpenTelemetry instrumentation setup for ERP Simulator.

Includes:
- OTLP exporter (gRPC)
- FastAPI auto-instrumentation
- Logging instrumentation
- Resource attributes (SmartOps standard)
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor


def configure_otel(app, service_name: str, environment: str) -> None:
    """
    Configure OTEL tracing & logging for FastAPI.

    Args:
        app: FastAPI application instance
        service_name: Name of this microservice
        environment: dev / stage / prod
    """

    otlp_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://otelcol-opentelemetry-collector:4317",
    )

    # -----------------------------
    # Tracer Provider
    # -----------------------------
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "smartops",
            "deployment.environment": environment,
            "service.version": "0.1.0",
        }
    )

    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # -----------------------------
    # Trace Exporter
    # -----------------------------
    span_exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=True,
    )

    span_processor = BatchSpanProcessor(span_exporter)
    provider.add_span_processor(span_processor)

    # -----------------------------
    # Instrument FastAPI + Logging
    # -----------------------------
    FastAPIInstrumentor().instrument_app(app)
    LoggingInstrumentor().instrument()

