import uuid

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import internal.core.telemetry as telemetry
from internal.core.agent.run_context import RunContext


def test_agent_llm_tool_spans_share_trace(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))

    class LLM:
        model_name = "fake"

        def stream(self, _messages):
            yield "chunk"

        def count_round_usage(self, _messages, _response):
            return 1, 1

        def get_pricing(self):
            return 0.0, 0.0, 1.0

    class Tool:
        def invoke(self, arguments):
            return arguments["value"]

    run_id = uuid.uuid4()
    with telemetry.agent_span(str(run_id), "test-agent"):
        list(telemetry.traced_llm_stream(LLM(), []))
        assert telemetry.invoke_tool(Tool(), {"value": 1}, "demo") == 1

    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == ["chat", "execute_tool", "invoke_agent"]
    assert len({span.context.trace_id for span in spans}) == 1
    chat = next(span for span in spans if span.name == "chat")
    assert chat.attributes["gen_ai.usage.input_tokens"] == 1
    assert chat.attributes["gen_ai.usage.output_tokens"] == 1
    provider.shutdown()


def test_agent_span_records_errors(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_tracer", provider.get_tracer("test"))

    import pytest

    with pytest.raises(RuntimeError, match="boom"):
        with telemetry.agent_span("run-1", "test-agent"):
            raise RuntimeError("boom")
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code.name == "ERROR"
    provider.shutdown()


def test_safe_path_masks_tokens_and_ids():
    path = "/web_apps/secret-token/chat/4bf92f35-777b-34da-6a3c-e929d0e0e4736/resume"
    safe = telemetry._safe_path(path)
    assert "secret-token" not in safe
    assert "4bf92f35-777b-34da-6a3c-e929d0e0e4736" not in safe
    assert "{token}" in safe


def test_run_context_propagates_traceparent():
    run_id = uuid.uuid4()
    ctx = RunContext(
        run_id=run_id,
        task_id=run_id,
        thread_id="message-1",
        traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    )
    config = ctx.config({"metadata": {"existing": 1}})
    assert config["configurable"]["thread_id"] == "message-1"
    assert config["metadata"]["traceparent"] == ctx.traceparent
    assert config["metadata"]["run_id"] == str(run_id)
