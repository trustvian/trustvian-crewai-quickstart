"""Instrumentation harness: stands in for the tracing a framework would ship.

Everything here reads the environment `trustvian dev` hands the child:
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT   where spans go (dev's Collector)
  OTEL_RESOURCE_ATTRIBUTES             deployment.environment.name=local
  OTEL_SERVICE_NAME                    the agent identity (from --agent)
  OTEL_SEMCONV_STABILITY_OPT_IN=http   new HTTP attribute names
  OTEL_BSP_SCHEDULE_DELAY              short batch flush

crew.py and tools.py never import any of this. The harness turns on three
instrumentors — CrewAI (agent/task/tool spans), LiteLLM (model calls) and
requests (the HTTP beneath each tool) — then runs crew.py unchanged.

Usage:  trustvian dev --instrumentation existing --agent support-crew -- python run.py
"""
import atexit
import os
import runpy
import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from openinference.instrumentation.crewai import CrewAIInstrumentor
from openinference.instrumentation.litellm import LiteLLMInstrumentor


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

    CrewAIInstrumentor().instrument(tracer_provider=provider)
    LiteLLMInstrumentor().instrument(tracer_provider=provider)
    RequestsInstrumentor().instrument(tracer_provider=provider)

    # Optional: direct OpenAI SDK usage (LLM_MODEL=openai/...).
    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument(tracer_provider=provider)
    except ImportError:
        pass

    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    runpy.run_path(os.path.join(here, "crew.py"), run_name="__main__")


if __name__ == "__main__":
    main()
