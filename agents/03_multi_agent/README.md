# Scenario 03 — Multi-agent (MAF `HandoffBuilder`) on ACA

A five-agent Microsoft Agent Framework workflow — **triage** plus three
inventory specialists and a **budget validator** — packaged as a single
container, served via `azure.ai.agentserver.agentframework.from_agent_framework(agent).run()`,
and fronted by the same APIM AI Gateway as scenario 02. The workflow is
registered in Foundry as a project connection so it's discoverable alongside
the Foundry-managed agents (scenarios 01 & 04).

## Topology

```
                    ┌──────────┐
                    │  triage  │   (start)
                    └────┬─────┘
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
  ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ flights  │    │  hotels  │    │   cars   │
  └────┬─────┘    └────┬─────┘    └────┬─────┘
       └───────────────┼─────────────────┘
                       ▼
                ┌────────────┐
                │   budget   │
                │ validator  │
                └─────┬──────┘
                      ▼
                   triage
```

Built with `agent_framework.orchestrations.HandoffBuilder`. Every participant
is a `chat_client.as_agent(...)` built from either `OpenAIChatClient` (APIM
route — production) or `FoundryChatClient` (AAD fallback). The workflow is
wrapped in a `WorkflowAgent` and exposed over the Responses API by
`from_agent_framework(agent).run()`.

## Flow

1. **Traveller query** hits APIM `/agents/maf/responses`.
2. APIM applies token limits + emit-token metric, routes to the ACA backend
   (`ca-maf-agent`).
3. `from_agent_framework` dispatches the request to the `WorkflowAgent`.
4. **Triage** decides which specialist(s) to hand off to based on the intent
   (flights / hotels / cars / combinations).
5. Each specialist uses its domain tool (`search_flights`, `search_hotels`,
   `search_car_rentals`), proposes 3 options, and hands back to triage.
6. Triage hands off to **budget validator**, which computes the total cost
   and checks it against the USD 3,500 corporate policy (or the traveller's
   stated budget).
7. Triage writes the final response to the traveller.

## Files

| File | Purpose |
|------|---|
| `src/agent_app.py` | `HandoffBuilder` topology, chat-client selection (APIM vs Foundry), tool functions, `from_agent_framework(...).run()` |
| `src/Dockerfile` | Python 3.12 slim, non-root, port 8088 |
| `src/requirements.txt` | `agent-framework`, `azure-ai-agentserver-agentframework`, pandas |
| `deploy_and_register.py` | ACR cloud build → `az containerapp update` → Foundry connection → smoke test |
| `scenario.py` | `build_handle()` for the shared scripts (calls APIM `/agents/maf` directly) |

## Run

```powershell
# 1) provision infra (once)
azd up

# 2) build + roll the real image + register the connection
python -m agents.03_multi_agent.deploy_and_register

# 3) exercise via shared scripts
python -m agents.shared.trace    --scenario 03_multi_agent
python -m agents.shared.evaluate --scenario 03_multi_agent
python -m agents.shared.redteam  --scenario 03_multi_agent
```

## Why this scenario matters

- **Multi-agent orchestration as a single endpoint.** The outside world sees
  one Responses API — internally it's a five-agent handoff graph with
  per-agent tracing spans (MAF emits OTel spans for every handoff, every
  tool call, every chat completion).
- **Separation of concerns.** Policy enforcement lives in its own agent
  (`budget_validator`) rather than buried in a single megaprompt. Swap the
  policy and the rest of the workflow is unchanged.
- **Same observability story as the other scenarios.** `trace` /
  `evaluate` / `redteam` target it exactly like scenarios 01, 02, and 04.

## Notes

### Initial placeholder image is expected

Like scenario 02, the ACA app `ca-maf-agent` is always provisioned by Bicep
with a public placeholder image (`mcr.microsoft.com/k8se/quickstart:latest`).
Requests to `/agents/maf` will respond with 503 until
`deploy_and_register.py` rolls the scenario image — this is expected and
harmless.

### Teardown

```powershell
python -m agents.03_multi_agent.cleanup
```

Deletes the Foundry project connection and rolls the ACA app back to the
placeholder image (and drops the APIM env vars + secret). The ACA app
itself is owned by Bicep and stays put. To tear everything down, run
`azd down` from the repo root (warning: that deletes the whole RG).
