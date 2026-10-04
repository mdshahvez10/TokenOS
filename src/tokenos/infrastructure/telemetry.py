import logging

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from structlog.types import EventDict, WrappedLogger

from tokenos.infrastructure.settings import Settings


def trace_context(
    logger: WrappedLogger,
    method_name: str,
    event: EventDict,
) -> EventDict:
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event["trace_id"] = format(context.trace_id, "032x")
        event["span_id"] = format(context.span_id, "016x")
    return event


def configure(settings: Settings) -> TracerProvider:
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            trace_context,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    if settings.otel_export:
        # Standard OTEL_EXPORTER_OTLP_* environment variables configure endpoint/auth.
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider
