# Scenario 02 — LangGraph on ACA via APIM AI Gateway

A LangGraph agent containerized, deployed to **Azure Container Apps**, fronted
by **APIM as an AI Gateway**, and registered as a **first-class asset** in the
Microsoft Foundry Control Plane.

This scenario showcases the BYO-agent story: customers own the container, the
framework, the hosting — and Foundry still provides a single pane of glass for
evaluation, red-teaming, tracing, and routing.

## Architecture

```
 caller ──► APIM /agents/langgraph/responses  (subscription-key auth,
              │                                 emits token metrics + logs)
              │
              ▼
         ACA: ca-langgraph-agent  (LangGraph on port 8088)
              │ model calls
              ▼
         APIM /openai/*  (MI auth, token-limit, emit-token-metric,
              │           circuit breaker)
              ▼
         Foundry model (gpt-5)
```

The agent's first-class asset in Foundry is a **project connection**
(`contoso-travel-langgraph-aca-endpoint`) pointing at the APIM `/agents/langgraph`
surface, with the subscription key stored in Key Vault. The shared eval/redteam
scripts invoke the APIM endpoint directly via the `openai` client — the Responses
API contract is already implemented by `from_langgraph(...).run()`.

> **Note:** `azure-ai-projects 2.0.0` does not yet ship a tool type that wraps
> an external Responses endpoint as a Foundry PromptAgent. When that surface
> lands, `scenario.py` can be switched to `agent_reference` without touching
> the rest of the code. For now the project connection is the asset.

## Files

| File | Purpose |
|------|---------|
| `src/agent_app.py` | LangGraph `StateGraph` + `from_langgraph` server on port 8088 |
| `src/Dockerfile` | Python 3.12 slim, non-root, healthcheck |
| `src/requirements.txt` | LangGraph + Agent Server adapter + Azure SDKs |
| `deploy_and_register.py` | ACR build → ACA revision update → Foundry connection |
| `scenario.py` | Adapter for the shared `trace` / `evaluate` / `redteam` scripts |

## Deploy

Prerequisites: `azd up` has provisioned Foundry, ACR, ACA env, Key Vault, APIM
(the bicep always deploys `ca-langgraph-agent` with a placeholder image so the
APIM backend and FQDN are stable); `scripts/setup-env.ps1` has hydrated `.env`.

```powershell
python -m agents.02_langgraph_aca.deploy_and_register
```

What it does:

1. **ACR cloud build** — `az acr build` (no local Docker).
2. **ACA revision update** — `az containerapp update` sets
   `AZURE_OPENAI_ENDPOINT=<APIM /openai URL>` and the APIM sub key (pulled
   from Key Vault) so the LangGraph model calls route through the gateway.
3. **Foundry connection** — `CustomKeys` connection holding the APIM agents
   subscription key, targetting `APIM_GATEWAY_URL/agents/langgraph`. The
   connection is visible in the Foundry portal as an external endpoint asset.
4. **Smoke test** — invokes the agent through the APIM `/agents/langgraph`
   Responses API.

## Use with the shared scripts

```powershell
python -m agents.shared.trace    --scenario 02_langgraph_aca
python -m agents.shared.evaluate --scenario 02_langgraph_aca
python -m agents.shared.redteam  --scenario 02_langgraph_aca
```

## Observability chain

Every user query produces three correlated trace sets:

| Stage | Signal |
|-------|--------|
| APIM `/agents/langgraph` | `ApiManagementGatewayLog` + diagnostic trace |
| ACA LangGraph container | Node/edge spans from `AIProjectInstrumentor` |
| APIM `/openai` | `ApiManagementGatewayLog` + `azure-openai-emit-token-metric` |

They correlate via the `x-apim-request-id` header that the `/agents` policy
propagates end-to-end.

## Key governance features demonstrated

- **Token quotas** per subscription via `azure-openai-token-limit`.
- **Emit-token-metric** into Application Insights for cost analytics.
- **Circuit breaker** on the Foundry backend for 429/5xx bursts.
- **Optional Entra ID audience validation** on `/agents` via `agentsJwtAudience`.
- **Managed-identity passthrough** for Foundry calls (no keys ever stored).

## Notes

### Initial placeholder image is expected

The ACA app `ca-langgraph-agent` is always provisioned by Bicep with a public
placeholder image (`mcr.microsoft.com/k8se/quickstart:latest`). This pins the
ingress FQDN and the APIM backend URL so the gateway wiring is stable from
the first `azd up`, even before the real agent image exists. The placeholder
serves on port 80, while the scenario image (and ACA ingress) uses port 8088
— **so requests to the `/agents/langgraph` surface will respond with 503
until `deploy_and_register.py` rolls the real image.** This 503 is expected
and harmless; it goes away as soon as the deploy script completes.

The same placeholder image is what `cleanup.py` rolls back to.

### Teardown

```powershell
python -m agents.02_langgraph_aca.cleanup
```

Deletes the Foundry project connection and rolls the ACA app back to the
placeholder image (and drops the APIM env vars + secret). The ACA app
itself is owned by Bicep and stays put. To tear everything down, run
`azd down` from the repo root — which deletes the entire resource group.

### Future SDK surface

When the Foundry SDK adds a `ConnectedAgentTool` (or equivalent external
agent target), `scenario.py` can switch to an `agent_reference` invocation
without any other code change.
