"""Instrumentation harness: stands in for the tracing a framework would ship.

Everything here reads the environment `trustvian dev` hands the child:
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT   where spans go (dev's Collector)
  OTEL_RESOURCE_ATTRIBUTES             deployment.environment.name=local
  OTEL_SERVICE_NAME                    the agent identity (from --agent)
  OTEL_SEMCONV_STABILITY_OPT_IN=http   new HTTP attribute names
  OTEL_BSP_SCHEDULE_DELAY              short batch flush

crew.py and tools.py never import any of this. The harness turns on
CrewAI (agent/task/tool spans), OpenAI (model calls: CrewAI reaches Ollama,
vLLM and OpenAI through the openai SDK), LiteLLM (model calls for providers
CrewAI still routes through LiteLLM, when it is installed) and requests (the
HTTP beneath each tool), then runs crew.py unchanged.

Usage:  trustvian dev --instrumentation existing --agent support-crew -- python run.py
"""
import atexit
import importlib.util
import os
import runpy
import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from openinference.instrumentation.crewai import CrewAIInstrumentor
from openinference.instrumentation.litellm import LiteLLMInstrumentor
from openinference.instrumentation.openai import OpenAIInstrumentor


# The CrewAI instrumentor also copies every task's description (the ticket
# text) onto the kickoff and task spans, and no OPENINFERENCE_HIDE_* option
# covers these attributes. They are dropped as they are set.
CREWAI_CONTENT_ATTRIBUTES = frozenset({
    "crew_tasks", "crew_inputs", "flow_inputs",
    "formatted_description", "formatted_expected_output",
})


class DropCrewAIContent(SpanProcessor):
    """Keeps CREWAI_CONTENT_ATTRIBUTES off every span, from its start."""

    def on_start(self, span, parent_context=None) -> None:
        set_attribute, set_attributes = span.set_attribute, span.set_attributes

        def keep_set_attribute(key, value):
            if key not in CREWAI_CONTENT_ATTRIBUTES:
                set_attribute(key, value)

        def keep_set_attributes(attributes):
            set_attributes({k: v for k, v in attributes.items() if k not in CREWAI_CONTENT_ATTRIBUTES})

        span.set_attribute, span.set_attributes = keep_set_attribute, keep_set_attributes


def instrument(provider: TracerProvider) -> None:
    """The instrumentors, on `provider`. The tests call this with an in-memory exporter."""
    provider.add_span_processor(DropCrewAIContent())
    CrewAIInstrumentor().instrument(tracer_provider=provider)
    OpenAIInstrumentor().instrument(tracer_provider=provider)
    RequestsInstrumentor().instrument(tracer_provider=provider)
    # LiteLLM is optional since CrewAI 1.x; instrumenting it when it is
    # absent only prints a warning.
    if importlib.util.find_spec("litellm"):
        LiteLLMInstrumentor().instrument(tracer_provider=provider)


def main() -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if not endpoint:
        sys.exit(
            "run.py: no OTLP endpoint in the environment — run this under "
            "`trustvian dev --instrumentation existing -- python run.py`"
        )
    print(f"run.py: exporter → {endpoint}", flush=True)

    # Resource.create() reads OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES;
    # OTLPSpanExporter() reads the endpoint and protocol variables; the batch
    # processor reads OTEL_BSP_SCHEDULE_DELAY. Nothing is hard-coded here.
    provider = TracerProvider(resource=Resource.create())
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    atexit.register(provider.shutdown)  # flush before the process exits

    instrument(provider)

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    runpy.run_path(os.path.join(here, "crew.py"), run_name="__main__")


if __name__ == "__main__":
    main()
