# Scenario 01 — Prompt Agent (Foundry-managed)

The simplest way to build an agent on Microsoft Foundry — declarative
instructions plus function tool schemas. The Foundry Responses API handles
routing; tool execution happens locally in the caller.

## Files

| File | Purpose |
|------|---------|
| `agent_def.py` | Shared agent definition (name, system prompt, tool schemas) |
| `create_and_invoke.py` | One-time bootstrap: creates the agent version and runs a few test queries |
| `scenario.py` | Adapter consumed by the shared `trace` / `evaluate` / `redteam` scripts |
| `cleanup.py` | Delete the agent from Foundry |

## Running

Bootstrap once (creates the agent):

```powershell
cd demo-agent-observability
python -m agents.01_prompt_agent.create_and_invoke
```

Then use the shared scripts with `--scenario 01_prompt_agent`:

```powershell
python -m agents.shared.trace    --scenario 01_prompt_agent
python -m agents.shared.evaluate --scenario 01_prompt_agent
python -m agents.shared.redteam  --scenario 01_prompt_agent
```

## Key concepts

- **PromptAgentDefinition** — declarative agent config with model, instructions, and tools
- **FunctionTool** — Python functions registered as tools via JSON schema
- **Tool-call loop** — detect `function_call` items → execute locally → return `FunctionCallOutput`
- **AIProjectInstrumentor** — auto-instruments Azure AI SDK calls for OpenTelemetry
