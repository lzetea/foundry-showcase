"""
Shared evaluation and red-team utilities.

Option A — *local generation, remote judges*
============================================

Foundry's ``azure_ai_target_completions`` data source requires a Foundry
**agent asset** target (``type: azure_ai_agent``). That works cleanly for
scenarios 01 and 04 (Foundry-managed PromptAgents) but not for scenarios 02
and 03, whose asset identity is a Foundry **project connection** pointing at
an APIM-fronted Responses endpoint — there is no PromptAgent to reference.

To run the same judges against all four scenarios, we:

1. **Generate responses locally** by calling ``handle.invoke(query)``. Every
   invoke is wrapped in an OTel span tagged with the evaluation run name and
   query, so the full agent trace (tool calls, handoffs, model hops) shows
   up in App Insights / Foundry Tracing and can be filtered by
   ``evaluation.run_name``.
2. **Submit the pre-generated items** to Foundry evals via a ``jsonl`` data
   source and map ``{{item.response}}`` into each evaluator's ``response``
   field (instead of ``{{sample.output_text}}``). No server-side generation,
   no target required.

The red-team path still goes through Foundry's server-side adversarial
generator (it needs the agent as a target to issue attacks). For scenarios
02 / 03 the shared red-team script therefore prints a clear "not-supported"
message pointing at the ``azure-ai-evaluation.RedTeam`` callback path until
Foundry exposes external agents as red-team targets.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from opentelemetry import trace

from openai.types.eval_create_params import DataSourceConfigCustom

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "contoso-travel"


def load_eval_data() -> list[dict]:
    """Load evaluation queries from the JSONL file."""
    data = []
    with open(DATA_DIR / "evaluation_data.jsonl") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line.strip()))
    return data


# =============================================================================
# Local generation (Option A)
# =============================================================================
def _configure_telemetry_once() -> None:
    """Best-effort: enable Azure Monitor export so invoke spans land in App
    Insights (and therefore the Foundry Tracing pane). No-op if the env var
    isn't set or if telemetry was already configured.
    """
    if getattr(_configure_telemetry_once, "_done", False):
        return
    conn = os.environ.get("TELEMETRY_CONNECTION_STRING", "").strip()
    if conn:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            from azure.ai.projects.telemetry import AIProjectInstrumentor

            os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
            os.environ.setdefault(
                "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true"
            )
            configure_azure_monitor(connection_string=conn)
            AIProjectInstrumentor().instrument()
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] telemetry setup failed (traces won't be exported): {exc}")
    _configure_telemetry_once._done = True  # type: ignore[attr-defined]


def _generate_locally(handle, run_name: str, suite: str, eval_data: list[dict]) -> list[dict]:
    """Call ``handle.invoke`` for every data row inside an OTel span.

    Returns a list of items with the live response attached. The span
    attributes (``evaluation.run_name``, ``evaluation.suite``,
    ``evaluation.query_index``) let you filter the Tracing pane and line
    each row up with the corresponding eval-run row in the Evaluations pane.
    """
    _configure_telemetry_once()
    tracer = trace.get_tracer(f"contoso-travel.eval.{suite}")

    enriched: list[dict] = []
    print(f"  Generating {len(eval_data)} response(s) via handle.invoke ...")
    for idx, row in enumerate(eval_data):
        query = row["query"]
        with tracer.start_as_current_span(f"eval.{suite}.invoke") as span:
            span.set_attribute("evaluation.run_name", run_name)
            span.set_attribute("evaluation.suite", suite)
            span.set_attribute("evaluation.query_index", idx)
            span.set_attribute("agent.scenario", handle.scenario)
            span.set_attribute("agent.name", handle.name)
            span.set_attribute("agent.version", str(handle.version))
            span.set_attribute("travel.query", query)
            try:
                output = handle.invoke(query) or ""
            except Exception as exc:  # noqa: BLE001
                span.record_exception(exc)
                output = f"[invoke failed: {exc}]"
            span.set_attribute("travel.response_length", len(output))
        enriched.append(
            {
                "query": query,
                "response": output,
                "context": row.get("context", ""),
                "ground_truth": row.get("ground_truth", ""),
            }
        )
    return enriched


def _poll_run(openai_client, eval_id: str, run_id: str, label: str = "Eval"):
    print(f"  Polling {label} run ...", end="", flush=True)
    while True:
        run = openai_client.evals.runs.retrieve(run_id=run_id, eval_id=eval_id)
        if run.status in ("completed", "failed", "canceled"):
            print(f" {run.status}")
            return run
        print(".", end="", flush=True)
        time.sleep(5)


def _print_results(openai_client, eval_id: str, run_id: str):
    items = list(
        openai_client.evals.runs.output_items.list(run_id=run_id, eval_id=eval_id)
    )
    print(f"\n  Results ({len(items)} items):")
    for item in items:
        results = {r.name: r.score for r in (item.results or [])}
        sample_input = ""
        if hasattr(item, "datasource_item") and item.datasource_item:
            sample_input = item.datasource_item.get("query", "")[:60]
        print(f"    Query: {sample_input:<60s}  Scores: {results}")
    return items


def _jsonl_data_source(items: list[dict]) -> dict:
    """Foundry ``jsonl`` data source with inline pre-generated items."""
    return {
        "type": "jsonl",
        "source": {
            "type": "file_content",
            "content": [{"item": item} for item in items],
        },
    }


# =============================================================================
# Quality evaluation
# =============================================================================
def run_quality_evaluation(openai_client, handle, model_name):
    """Fluency + coherence + task adherence, local generation, remote judges."""
    print("\n--- Quality Evaluation ---")
    run_name = f"Quality Run – {handle.scenario} – {handle.version}"
    items = _generate_locally(handle, run_name, "quality", load_eval_data())

    quality_eval = openai_client.evals.create(
        name=f"Quality Eval – {handle.name}",
        data_source_config=DataSourceConfigCustom(
            type="custom",
            item_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "response": {"type": "string"},
                },
                "required": ["query", "response"],
            },
            include_sample_schema=False,
        ),
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": "fluency",
                "evaluator_name": "builtin.fluency",
                "initialization_parameters": {"deployment_name": model_name},
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "coherence",
                "evaluator_name": "builtin.coherence",
                "initialization_parameters": {"deployment_name": model_name},
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "task_adherence",
                "evaluator_name": "builtin.task_adherence",
                "initialization_parameters": {"deployment_name": model_name},
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
        ],
    )
    print(f"  Created eval: {quality_eval.id}")
    run = openai_client.evals.runs.create(
        eval_id=quality_eval.id,
        name=run_name,
        data_source=_jsonl_data_source(items),
    )
    print(f"  Started run: {run.id}")

    run = _poll_run(openai_client, quality_eval.id, run.id, "Quality")
    return _print_results(openai_client, quality_eval.id, run.id)


# =============================================================================
# Safety evaluation
# =============================================================================
def run_safety_evaluation(openai_client, handle):
    """Violence + hate/unfairness + self-harm; no model deployment required."""
    print("\n--- Safety Evaluation ---")
    run_name = f"Safety Run – {handle.scenario} – {handle.version}"
    items = _generate_locally(handle, run_name, "safety", load_eval_data())

    safety_eval = openai_client.evals.create(
        name=f"Safety Eval – {handle.name}",
        data_source_config=DataSourceConfigCustom(
            type="custom",
            item_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "response": {"type": "string"},
                },
                "required": ["query", "response"],
            },
            include_sample_schema=False,
        ),
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": "violence",
                "evaluator_name": "builtin.violence",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "hate_unfairness",
                "evaluator_name": "builtin.hate_unfairness",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "self_harm",
                "evaluator_name": "builtin.self_harm",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
        ],
    )
    print(f"  Created eval: {safety_eval.id}")
    run = openai_client.evals.runs.create(
        eval_id=safety_eval.id,
        name=run_name,
        data_source=_jsonl_data_source(items),
    )
    print(f"  Started run: {run.id}")

    run = _poll_run(openai_client, safety_eval.id, run.id, "Safety")
    return _print_results(openai_client, safety_eval.id, run.id)


# =============================================================================
# Agentic performance evaluation
# =============================================================================
def run_agentic_evaluation(openai_client, handle):
    """Intent resolution + groundedness + relevance."""
    print("\n--- Agentic Performance Evaluation ---")
    run_name = f"Agentic Run – {handle.scenario} – {handle.version}"
    items = _generate_locally(handle, run_name, "agentic", load_eval_data())

    agentic_eval = openai_client.evals.create(
        name=f"Agentic Eval – {handle.name}",
        data_source_config=DataSourceConfigCustom(
            type="custom",
            item_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "response": {"type": "string"},
                    "context": {"type": "string"},
                    "ground_truth": {"type": "string"},
                },
                "required": ["query", "response"],
            },
            include_sample_schema=False,
        ),
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": "intent_resolution",
                "evaluator_name": "builtin.intent_resolution",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "groundedness",
                "evaluator_name": "builtin.groundedness",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                    "context": "{{item.context}}",
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "relevance",
                "evaluator_name": "builtin.relevance",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
        ],
    )
    print(f"  Created eval: {agentic_eval.id}")
    run = openai_client.evals.runs.create(
        eval_id=agentic_eval.id,
        name=run_name,
        data_source=_jsonl_data_source(items),
    )
    print(f"  Started run: {run.id}")

    run = _poll_run(openai_client, agentic_eval.id, run.id, "Agentic")
    return _print_results(openai_client, agentic_eval.id, run.id)


# =============================================================================
# Red-team evaluation
# =============================================================================
# Scenarios whose agent is a Foundry PromptAgent (``azure_ai_agent`` target).
# Red-team requires a server-side adversarial generator that can issue attacks
# at the target; external connection-backed agents (02 / 03) are not yet
# supported by this surface.
_REDTEAM_SUPPORTED_SCENARIOS = {"01_prompt_agent", "04_foundry_tools_agent"}


def run_redteam(project_client, openai_client, handle):
    """Adversarial red-team scan.

    Supported for Foundry-managed PromptAgents (scenarios 01 / 04). For
    connection-backed scenarios (02 / 03) this prints a clear message and
    returns, because ``AzureAIAgentTarget(name, version)`` only resolves
    Foundry-registered agent assets — not external project connections.
    """
    if handle.scenario not in _REDTEAM_SUPPORTED_SCENARIOS:
        print("\n--- Red-Team Evaluation ---")
        print(f"  [skip] scenario {handle.scenario!r} uses a Foundry project")
        print("         connection (not an ``azure_ai_agent`` target), which")
        print("         the server-side red-team orchestrator does not yet")
        print("         support.")
        print("         Extension path: use the callback-based red-team in")
        print("         ``azure-ai-evaluation.red_team.RedTeam`` with")
        print("         ``handle.invoke`` as the target. See")
        print("         https://learn.microsoft.com/azure/foundry/concepts/ai-red-teaming-agent")
        return None

    from azure.ai.projects.models import (
        AgentTaxonomyInput,
        AzureAIAgentTarget,
        EvaluationTaxonomy,
        RiskCategory,
    )

    print("\n--- Red-Team Evaluation ---")

    target = AzureAIAgentTarget(name=handle.name, version=handle.version)

    print("  Generating evaluation taxonomy ...")
    taxonomy = project_client.beta.evaluation_taxonomies.create(
        name=handle.name,
        body=EvaluationTaxonomy(
            description=f"Red-team taxonomy for {handle.name}",
            taxonomy_input=AgentTaxonomyInput(
                risk_categories=[RiskCategory.PROHIBITED_ACTIONS],
                target=target,
            ),
        ),
    )
    print(f"  Taxonomy created: {taxonomy.id}")

    red_team_eval = openai_client.evals.create(
        name=f"Red Team – {handle.name}",
        data_source_config={"type": "azure_ai_source", "scenario": "red_team"},
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": "Prohibited Actions",
                "evaluator_name": "builtin.prohibited_actions",
                "evaluator_version": "1",
            },
            {
                "type": "azure_ai_evaluator",
                "name": "Task Adherence",
                "evaluator_name": "builtin.task_adherence",
                "evaluator_version": "1",
            },
            {
                "type": "azure_ai_evaluator",
                "name": "Sensitive Data Leakage",
                "evaluator_name": "builtin.sensitive_data_leakage",
                "evaluator_version": "1",
            },
        ],
    )
    print(f"  Created red-team eval: {red_team_eval.id}")

    run = openai_client.evals.runs.create(
        eval_id=red_team_eval.id,
        name=f"Red Team Run – {handle.name}",
        data_source={
            "type": "azure_ai_red_team",
            "item_generation_params": {
                "type": "red_team_taxonomy",
                "attack_strategies": ["Flip", "Base64", "IndirectJailbreak"],
                "num_turns": 5,
                "source": {"type": "file_id", "id": taxonomy.id},
            },
            "target": target.as_dict(),
        },
    )
    print(f"  Started red-team run: {run.id}")

    run = _poll_run(openai_client, red_team_eval.id, run.id, "Red-Team")
    return _print_results(openai_client, red_team_eval.id, run.id)
