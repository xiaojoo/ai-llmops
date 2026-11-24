from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import context, metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from internal.config.settings import get_settings

_tracer = trace.get_tracer("llmops")
_meter = metrics.get_meter("llmops")
_initialized = False
_counters: dict[str, Any] = {}
_histograms: dict[str, Any] = {}


def init_telemetry() -> None:
    global _tracer, _meter, _initialized
    if _initialized:
        return
    settings = get_settings()
    if not settings.otel_enabled:
        _initialized = True
        return
    resource = Resource.create({"service.name": settings.otel_service_name})
    tracer_provider = TracerProvider(resource=resource)
    exporters = {item.strip().lower() for item in settings.otel_exporters.split(",")}
    if "console" in exporters:
        tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    if "otlp" in exporters:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer("llmops")

    readers = []
    if "console" in exporters:
        readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))
    if "otlp" in exporters:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter("llmops")
    _initialized = True


def shutdown_telemetry() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        provider.shutdown()
    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
        meter_provider.shutdown()


def current_trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.trace_id, "032x") if span_context.is_valid else ""


def current_traceparent() -> str:
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier.get("traceparent", "")


@contextmanager
def attach_traceparent(traceparent: str) -> Iterator[None]:
    if not traceparent:
        yield
        return
    ctx = TraceContextTextMapPropagator().extract({"traceparent": traceparent})
    token = context.attach(ctx)
    try:
        yield
    finally:
        context.detach(token)


def _counter(name: str):
    if name not in _counters:
        _counters[name] = _meter.create_counter(name)
    return _counters[name]


def _histogram(name: str):
    if name not in _histograms:
        _histograms[name] = _meter.create_histogram(name)
    return _histograms[name]


def _set_error(span: Span, exc: Exception) -> None:
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)[:500]))


@contextmanager
def agent_span(run_id: str, agent_name: str) -> Iterator[Span]:
    started = time.perf_counter()
    with _tracer.start_as_current_span("invoke_agent") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", agent_name)
        span.set_attribute("llmops.run_id", run_id)
        try:
            yield span
        except Exception as exc:
            _set_error(span, exc)
            _counter("llmops.agent.errors").add(1, {"agent": agent_name})
            raise
        finally:
            _histogram("llmops.agent.duration").record(time.perf_counter() - started, {"agent": agent_name})
            _counter("llmops.agent.runs").add(1, {"agent": agent_name})


def traced_llm_stream(llm: Any, messages: Any):
    model_name = str(getattr(llm, "model_name", "") or "unknown")
    with llm_span(model_name) as span:
        chunks = []
        for chunk in llm.stream(messages):
            chunks.append(chunk)
            yield chunk
        input_tokens, output_tokens = llm.count_round_usage(messages, chunks)
        cost = None
        if input_tokens is not None and output_tokens is not None:
            input_price, output_price, unit = llm.get_pricing()
            cost = (input_tokens * input_price + output_tokens * output_price) * unit
        record_llm_usage(span, input_tokens, output_tokens, cost)


@contextmanager
def llm_span(model_name: str) -> Iterator[Span]:
    started = time.perf_counter()
    with _tracer.start_as_current_span("chat") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model_name)
        try:
            yield span
        except Exception as exc:
            _set_error(span, exc)
            raise
        finally:
            _histogram("llmops.llm.duration").record(time.perf_counter() - started, {"model": model_name})


def record_llm_usage(span: Span, input_tokens: int | None, output_tokens: int | None, cost: float | None) -> None:
    if not span.is_recording():
        return
    labels = {"model": span.attributes.get("gen_ai.request.model", "unknown")}
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        _counter("llmops.llm.input_tokens").add(input_tokens, labels)
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        _counter("llmops.llm.output_tokens").add(output_tokens, labels)
    if cost is not None:
        span.set_attribute("gen_ai.usage.cost", cost)
        _counter("llmops.llm.cost").add(cost, labels)


def invoke_tool(tool: Any, arguments: Any, tool_name: str) -> Any:
    with tool_span(tool_name):
        return tool.invoke(arguments)


@contextmanager
def tool_span(tool_name: str) -> Iterator[Span]:
    started = time.perf_counter()
    with _tracer.start_as_current_span("execute_tool") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool_name)
        try:
            yield span
        except Exception as exc:
            _set_error(span, exc)
            _counter("llmops.tool.errors").add(1, {"tool": tool_name})
            raise
        finally:
            _histogram("llmops.tool.duration").record(time.perf_counter() - started, {"tool": tool_name})
            _counter("llmops.tool.calls").add(1, {"tool": tool_name})


def _safe_path(path: str) -> str:
    path = re.sub(r"(/web_apps/)[^/]+", r"\1{token}", path)
    path = re.sub(r"(/apps/)[0-9a-fA-F-]{36}", r"\1{app_id}", path)
    path = re.sub(r"(/conversations/)[0-9a-fA-F-]{36}", r"\1{conversation_id}", path)
    path = re.sub(r"(/datasets/)[0-9a-fA-F-]{36}", r"\1{dataset_id}", path)
    path = re.sub(r"(/chat/)[0-9a-fA-F-]{36}", r"\1{run_id}", path)
    path = re.sub(r"(/tasks/)[0-9a-fA-F-]{36}", r"\1{task_id}", path)
    return path


class TelemetryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        carrier = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        ctx = TraceContextTextMapPropagator().extract(carrier)
        token = context.attach(ctx)
        try:
            safe_path = _safe_path(scope.get("path", "/"))
            with _tracer.start_as_current_span(
                f"{scope.get('method', 'HTTP')} {safe_path}",
                kind=trace.SpanKind.SERVER,
            ) as span:
                span.set_attribute("http.request.method", scope.get("method", ""))
                span.set_attribute("url.path", safe_path)
                await self.app(scope, receive, send)
        except Exception as exc:
            _set_error(span, exc)
            raise
        finally:
            context.detach(token)
            _histogram("llmops.http.duration").record(time.perf_counter() - started)
