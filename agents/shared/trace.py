"""
Unified tracing entrypoint.

Usage:
    python -m agents.shared.trace --scenario 01_prompt_agent
    python -m agents.shared.trace --scenario 02_langgraph_aca --mode azure-monitor

The scenario adapter's ``invoke(query)`` is called inside OTel spans. Part A
emits to the console, Part B emits to Application Insights (same App Insights
instance Foundry uses — traces appear in the Foundry portal's Tracing tab).
"""

from __future__ import annotations

import argparse
import os
import sys

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from azure.ai.projects.telemetry import AIProjectInstrumentor

from agents.shared.config import get_clients
from agents.shared.registry import SCENARIOS, get_handle

os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")


SAMPLE_QUERIES: list[tuple[str, str]] = [
    ("What flights go from Seattle to Paris?", "seattle-paris-flights"),
    ("Find me a luxury hotel in Paris with a pool.", "paris-luxury-hotel"),
    ("I need a cheap car rental in Cancun.", "cancun-car-rental"),
]


def _run_spans(handle, tracer, queries):
    for query, label in queries:
        with tracer.start_as_current_span(f"{handle.scenario}-{label}") as span:
            span.set_attribute("travel.query", query)
            span.set_attribute("travel.scenario", handle.scenario)
            span.set_attribute("travel.agent_name", handle.name)
            print(f"\nUser: {query}")
            output = handle.invoke(query)
            span.set_attribute("travel.response_length", len(output or ""))
            print(f"Assistant: {(output or '')[:200]}...")


def _console_mode(handle):
    print("\n" + "=" * 70)
    print(f"Console tracing — scenario {handle.scenario}")
    print("=" * 70)
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)
    AIProjectInstrumentor().instrument()
    try:
        tracer = trace.get_tracer(f"contoso-travel-{handle.scenario}-console")
        _run_spans(handle, tracer, SAMPLE_QUERIES[:1])
    finally:
        tracer_provider.shutdown()
        AIProjectInstrumentor().uninstrument()


def _azure_monitor_mode(handle):
    from azure.monitor.opentelemetry import configure_azure_monitor

    project_client, _ = get_clients()
    connection_string = (
        os.environ.get("TELEMETRY_CONNECTION_STRING")
        or project_client.telemetry.get_application_insights_connection_string()
    )
    if not connection_string:
        print("ERROR: No Application Insights connection string found.", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 70)
    print(f"Azure Monitor tracing — scenario {handle.scenario}")
    print(f"App Insights: {connection_string[:50]}...")
    print("=" * 70)

    configure_azure_monitor(connection_string=connection_string)
    AIProjectInstrumentor().instrument()
    try:
        tracer = trace.get_tracer(f"contoso-travel-{handle.scenario}-azmon")
        _run_spans(handle, tracer, SAMPLE_QUERIES)
    finally:
        AIProjectInstrumentor().uninstrument()

    print("\nTraces sent to Application Insights. View them in the Foundry portal → Tracing.")


def main():
    parser = argparse.ArgumentParser(description="Unified agent tracing.")
    parser.add_argument(
        "--scenario",
        required=True,
        choices=SCENARIOS,
        help="Which scenario to trace.",
    )
    parser.add_argument(
        "--mode",
        choices=["console", "azure-monitor", "both"],
        default="both",
        help="Tracing backend (default: both).",
    )
    args = parser.parse_args()

    handle = get_handle(args.scenario)
    print(f"Agent: {handle.name} (version {handle.version})")

    if args.mode in ("console", "both"):
        _console_mode(handle)
    if args.mode in ("azure-monitor", "both"):
        _azure_monitor_mode(handle)


if __name__ == "__main__":
    main()
