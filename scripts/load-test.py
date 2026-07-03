#!/usr/bin/env python3
"""Load-test a Contoso Travel scenario to seed traces for the observe / continuous-eval story.

Adapted from the Microsoft Build LAB540 workshop's load-test script. The goal is
**not** benchmarking - it is to generate enough agent traffic that Application
Insights / Foundry Tracing has real conversations to cluster, and continuous
evaluation has a population of production-like traffic to sample.

Each request runs through the shared scenario adapter's ``handle.invoke`` (the
same path trace.py / evaluate.py use) inside an OpenTelemetry span tagged with
the load-test run id, so every call shows up in the Foundry Tracing pane and can
be filtered by ``loadtest.run_id``.

Usage (from the repo root, after ``azd up`` + scripts/setup-env.ps1):

    # 50 requests, 5 concurrent, against the prompt agent
    python scripts/load-test.py --scenario 01_prompt_agent

    # heavier run against the multi-agent endpoint
    python scripts/load-test.py --scenario 03_multi_agent --total 100 --concurrency 10

Per-request results (latency, status, response preview) are written under
``logs/loadtest/``. The targeted scenario must already be deployed/registered.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Make ``agents`` importable when run as ``python scripts/load-test.py``.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from opentelemetry import trace  # noqa: E402

from agents.shared.registry import SCENARIOS, get_handle  # noqa: E402

DEFAULT_PROMPTS = REPO_ROOT / "data" / "contoso-travel" / "sample_prompts.jsonl"
EVAL_PROMPTS = REPO_ROOT / "data" / "contoso-travel" / "evaluation_data.jsonl"
RESULTS_DIR = REPO_ROOT / "logs" / "loadtest"


def _configure_telemetry() -> bool:
    """Enable Azure Monitor export so load-test spans reach App Insights.

    Returns ``True`` if telemetry was configured, ``False`` when no connection
    string is available or setup failed.
    """
    conn = os.environ.get("TELEMETRY_CONNECTION_STRING", "").strip()
    if not conn:
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from azure.ai.projects.telemetry import AIProjectInstrumentor

        os.environ.setdefault("AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING", "true")
        os.environ.setdefault(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true"
        )
        configure_azure_monitor(connection_string=conn)
        AIProjectInstrumentor().instrument()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] telemetry setup failed (traces won't export): {exc}")
        return False


def _load_prompts(path: Path) -> list[str]:
    """Load prompt strings from a JSONL file (``prompt`` or ``query`` key)."""
    prompts: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = row.get("prompt") or row.get("query")
            if text:
                prompts.append(text)
    return prompts


def _invoke_with_retry(handle, prompt: str, attempts: int = 3) -> str:
    """Invoke the agent, retrying transient telemetry-instrumentor glitches.

    The azure-ai-projects Responses instrumentor occasionally reads
    ``.attributes`` on a ``NonRecordingSpan`` under thread-pool concurrency and
    raises ``AttributeError`` even though the underlying model call is fine, so a
    short retry recovers cleanly. Any other error propagates on the first try.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return handle.invoke(prompt) or ""
        except AttributeError as exc:
            if "attributes" not in str(exc).lower():
                raise
            last_exc = exc
            time.sleep(0.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def _run_one(handle, tracer, run_id: str, idx: int, prompt: str) -> dict:
    """Invoke the agent once inside a tagged OTel span; return a result row."""
    start = time.perf_counter()
    status = "ok"
    error = ""
    output = ""
    with tracer.start_as_current_span("loadtest.invoke") as span:
        span.set_attribute("loadtest.run_id", run_id)
        span.set_attribute("loadtest.request_index", idx)
        span.set_attribute("agent.scenario", handle.scenario)
        span.set_attribute("agent.name", handle.name)
        span.set_attribute("travel.query", prompt)
        try:
            output = _invoke_with_retry(handle, prompt)
        except Exception as exc:  # noqa: BLE001
            status = "error"
            error = str(exc)
            span.record_exception(exc)
        latency_ms = (time.perf_counter() - start) * 1000.0
        span.set_attribute("loadtest.latency_ms", latency_ms)
        span.set_attribute("loadtest.status", status)
    return {
        "index": idx,
        "status": status,
        "latency_ms": round(latency_ms, 1),
        "prompt": prompt,
        "response_preview": output[:200],
        "error": error,
    }


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = min(len(sorted_values) - 1, int(round(pct / 100.0 * (len(sorted_values) - 1))))
    return sorted_values[k]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load-test a Contoso Travel scenario to seed traces."
    )
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    parser.add_argument(
        "--total", type=int, default=50, help="Total requests to send (default: 50)."
    )
    parser.add_argument(
        "--concurrency", type=int, default=5, help="Concurrent workers (default: 5)."
    )
    parser.add_argument(
        "--prompts",
        type=Path,
        default=None,
        help="JSONL prompt source (default: sample_prompts.jsonl, else evaluation_data.jsonl).",
    )
    parser.add_argument(
        "--no-telemetry",
        action="store_true",
        help="Skip Azure Monitor export (local console-only run).",
    )
    args = parser.parse_args()

    prompts_path = args.prompts or (
        DEFAULT_PROMPTS if DEFAULT_PROMPTS.exists() else EVAL_PROMPTS
    )
    prompts = _load_prompts(prompts_path)
    if not prompts:
        print(f"ERROR: no prompts found in {prompts_path}", file=sys.stderr)
        sys.exit(1)

    telemetry_on = False if args.no_telemetry else _configure_telemetry()
    tracer = trace.get_tracer("contoso-travel.loadtest")

    print("=" * 70)
    print(f"Load test - scenario {args.scenario}")
    print(f"  prompts source : {prompts_path.name} ({len(prompts)} unique)")
    print(f"  total requests : {args.total}")
    print(f"  concurrency    : {args.concurrency}")
    print(f"  telemetry      : {'on (App Insights)' if telemetry_on else 'off'}")
    print("=" * 70)

    handle = get_handle(args.scenario)
    run_id = f"loadtest-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    print(f"  agent          : {handle.name} (run_id {run_id})\n")

    # Cycle through the prompt pool to reach --total requests.
    work = [(i, prompts[i % len(prompts)]) for i in range(args.total)]
    results: list[dict] = []
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(_run_one, handle, tracer, run_id, idx, prompt)
            for idx, prompt in work
        ]
        for done, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            results.append(res)
            print("." if res["status"] == "ok" else "x", end="", flush=True)
            if done % 50 == 0:
                print(f"  {done}/{args.total}")
    elapsed = time.perf_counter() - started
    print()

    ok = [r for r in results if r["status"] == "ok"]
    errors = [r for r in results if r["status"] != "ok"]
    latencies = sorted(r["latency_ms"] for r in ok)

    print("\n" + "-" * 70)
    print(f"  done in {elapsed:.1f}s  |  ok {len(ok)}  errors {len(errors)}")
    if latencies:
        print(
            f"  latency ms  p50 {_percentile(latencies, 50):.0f}"
            f"  p90 {_percentile(latencies, 90):.0f}"
            f"  p99 {_percentile(latencies, 99):.0f}"
            f"  max {latencies[-1]:.0f}"
        )
    if errors:
        print(f"  first error: {errors[0]['error'][:160]}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{run_id}.json"
    out_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "scenario": args.scenario,
                "agent": handle.name,
                "total": args.total,
                "concurrency": args.concurrency,
                "elapsed_s": round(elapsed, 1),
                "ok": len(ok),
                "errors": len(errors),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  results -> {out_path.relative_to(REPO_ROOT)}")

    if telemetry_on:
        print(
            "  Traces sent to App Insights - filter the Foundry Tracing pane by "
            "loadtest.run_id."
        )
        provider = trace.get_tracer_provider()
        try:
            provider.force_flush()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            time.sleep(5)
    print("-" * 70)


if __name__ == "__main__":
    main()
