# Scenario 04 — Foundry-managed agent with built-in tools

A Foundry **prompt agent** that uses only **server-side tools** — no
container, no function-tool dispatch loop, no custom host. The customer
brings domain knowledge (policy docs) and intent (instructions); Foundry
runs the vector search, the sandboxed Python, and the web search.

This scenario is the counterpoint to scenario 02 (BYO container behind an
AI Gateway): same observability surface, completely different operational
model.

## Tools

| Tool | What it does | Dependency |
|------|---|---|
| `file_search` | Grounded retrieval from a vector store of Contoso Travel policy docs (baggage, loyalty, insurance, visas) | Auto-provisioned by `agent_def.ensure_vector_store` on first run |
| `code_interpreter` | Sandboxed Python for itinerary math, mile redemption, currency | Always on |
| `bing_grounding` | Real-time web search for current conditions | **Optional.** Set `BING_GROUNDING_CONNECTION_ID` to the Foundry project-connection id of a Bing Grounding resource. |

## Files

| File | Purpose |
|------|---|
| `agent_def.py` | System prompt, tool assembly, vector-store lifecycle |
| `create_and_invoke.py` | Creates the agent version and runs three demo queries |
| `scenario.py` | `build_handle()` for the shared scripts |
| `cleanup.py` | Deletes the agent, vector store, and uploaded files |
| `data/*.md` | Travel policy documents that become the vector store |

## Run

```powershell
python -m agents.04_foundry_tools_agent.create_and_invoke
```

First run uploads the policy docs, creates the vector store, and persists
its id to `.vector_store_id` so subsequent runs re-use it.

Then target the scenario from the shared scripts exactly like every other:

```powershell
python -m agents.shared.trace    --scenario 04_foundry_tools_agent
python -m agents.shared.evaluate --scenario 04_foundry_tools_agent
python -m agents.shared.redteam  --scenario 04_foundry_tools_agent
```

### Enabling Bing Grounding

1. In the Foundry portal, create a **Grounding with Bing Search** resource
   and attach it as a connection to your project.
2. Copy the connection resource id and export:
   ```powershell
   $env:BING_GROUNDING_CONNECTION_ID = "/subscriptions/.../connections/<name>"
   ```
3. Re-run `create_and_invoke.py` — the next agent version will include the
   `bing_grounding` tool.

## Teardown

```powershell
python -m agents.04_foundry_tools_agent.cleanup
```

## Why this scenario matters

- **Zero infrastructure.** No ACR, no ACA, no APIM, no JWT. Just instructions
  + a folder of markdown.
- **Server-side tool execution.** The client only sees the final answer;
  retrieval and Python execution happen inside Foundry with automatic
  tracing spans (`file_search`, `code_interpreter`, `bing_grounding`).
- **Evaluation parity.** The same `evaluate` / `redteam` scripts that target
  the ACA-hosted LangGraph agent (scenario 02) and the multi-agent
  HandoffBuilder (scenario 03) work unchanged here.
