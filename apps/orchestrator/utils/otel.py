"""
OpenTelemetry setup for SmartOps Orchestrator.

- Configures OTLP exporter (gRPC) to collector.
- Instruments FastAPI + logging + outgoing HTTP calls.
"""

from __future__ import annotations

import os
import logging

from fastapi import FastAPI

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_otel(app: FastAPI) -> None:
    """
    Configure OpenTelemetry for the orchestrator service.

    Reads OTLP endpoint from:
      - OTEL_EXPORTER_OTLP_ENDPOINT (default: http://smartops-otelcol:4317)
    """

    service_name = os.getenv("OTEL_SERVICE_NAME", "smartops-orchestrator")
    environment = os.getenv("SMARTOPS_ENV", "dev")
    namespace = os.getenv("SMARTOPS_NAMESPACE", "smartops-dev")

    otlp_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://smartops-otelcol:4317",
    )

    # 1) TracerProvider with resource
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": namespace,
            "deployment.environment": environment,
            "service.version": "0.1.0",
            "smartops.component": "orchestrator",
        }
    )

    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # 2) OTLP gRPC exporter
    span_exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=True,
    )

    span_processor = BatchSpanProcessor(span_exporter)
    provider.add_span_processor(span_processor)

    # 3) Instrument FastAPI, logging, and outgoing HTTP
    FastAPIInstrumentor().instrument_app(app)

    LoggingInstrumentor().instrument(
        set_logging_format=True,
    )

    RequestsInstrumentor().instrument()

    # 4) Configure Python logging root level (INFO by default)
    logging.basicConfig(
        level=os.getenv("ORCHESTRATOR_LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

