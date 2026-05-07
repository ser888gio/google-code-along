"""OTel TracerProvider + MeterProvider wired to GCP Cloud Trace / Cloud Monitoring.

Call `setup_telemetry(app)` once at startup, before any requests are served.
On Cloud Run, X-Cloud-Trace-Context is injected automatically by the platform,
so trace/log correlation works without additional configuration.
Outside GCP (local dev), the providers fall back to the NOOP exporters — no
credentials error is raised.
"""

from __future__ import annotations

import os

from opentelemetry import metrics, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_SENTINEL = object()
_initialized = False


def _gcp_resource() -> Resource:
    service = os.getenv("K_SERVICE", "rs-generator-backend")
    revision = os.getenv("K_REVISION", "local")
    return Resource.create({SERVICE_NAME: service, "service.version": revision})


def setup_telemetry(app=None) -> None:  # noqa: ANN001
    """Initialize OTel providers and instrument the FastAPI app.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _initialized  # noqa: PLW0603
    if _initialized:
        return
    _initialized = True

    resource = _gcp_resource()

    # --- Tracing ---
    tracer_provider = TracerProvider(resource=resource)
    try:
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        tracer_provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter())
        )
    except Exception:
        # Credentials not available (local dev) — traces are still collected
        # in memory; they just won't be exported.
        pass

    trace.set_tracer_provider(tracer_provider)

    # --- Metrics ---
    try:
        from opentelemetry.exporter.cloud_monitoring import (
            CloudMonitoringMetricsExporter,
        )

        reader = PeriodicExportingMetricReader(
            CloudMonitoringMetricsExporter(),
            export_interval_millis=60_000,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    except Exception:
        meter_provider = MeterProvider(resource=resource)

    metrics.set_meter_provider(meter_provider)

    # --- FastAPI auto-instrumentation ---
    if app is not None:
        FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str = "rs-generator") -> trace.Tracer:
    return trace.get_tracer(name)


def get_meter(name: str = "rs-generator") -> metrics.Meter:
    return metrics.get_meter(name)
