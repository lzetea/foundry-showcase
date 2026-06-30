# Microsoft Foundry — End-to-End Showcase

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Bicep](https://img.shields.io/badge/IaC-Bicep%20%2B%20AVM-0078d4.svg)](infra/)
[![CI](https://github.com/lzetea/foundry-showcase/actions/workflows/ci.yml/badge.svg)](https://github.com/lzetea/foundry-showcase/actions/workflows/ci.yml)

A single Contoso Travel scenario implemented as four progressively richer agent
architectures, all unified under the **Microsoft Foundry Control Plane** — so
you can stand up a Foundry environment in one command and explore its **agentic** (Prompt Agents, built-in tools, multi-agent, BYO via
AI Gateway) and **governance** (tracing, evals, red-teaming) capabilities
end-to-end.

> **Status — personal demo repo.** PoC defaults throughout: no private
> networking, APIM `/agents` JWT validation off by default, Key Vault purge
> protection disabled, Cosmos serverless single-region, ACA on a public
> placeholder image until per-scenario `deploy_and_register.py` rolls the real
> one. Pinned to current Foundry SDK surfaces (`azure-ai-projects` 2.0.0b3-b4,
> `azure-ai-agentserver-*==1.0.0b17`), some of which are still in beta — pin
> deliberately or upgrade with care. Not production-ready as shipped; see the
> [PoC-friendly defaults](#poc-friendly-defaults-revisit-before-production)
> section for what to harden before any non-demo use.

A turnkey **Microsoft Foundry environment** plus a hands-on showcase of its
**agentic** and **governance** capabilities — all under a single `azd up`.

### TL;DR

```powershell
git clone <repo> && cd demo-agent-observability
.\scripts\azd-prep.ps1 -EnvName foundry-demo -Location eastus2
azd up                                            # provision the sandbox (~30-45 min with APIM)
pip install -r requirements.txt; .\scripts\setup-env.ps1
python -m agents.01_prompt_agent.create_and_invoke  # first agent, end-to-end
```

> Deploying with an agent? Follow the deterministic runbook in
> [DEPLOY_AGENT.md](DEPLOY_AGENT.md) instead.

### What you get

- **A complete Foundry sandbox** (Bicep + Azure Verified Modules): Foundry
  account & project, a model deployment, Application Insights, Container
  Registry, Key Vault, Cosmos DB, Azure AI Search, an APIM AI Gateway, and an
  Azure Container Apps environment — RBAC pre-wired for your user and the agent
  runtimes.
- **Four reference agents** on one Contoso Travel scenario, running
  side-by-side so you compare architectures, not just frameworks: a
  Foundry-managed Prompt Agent (function tools), a Prompt Agent with Foundry
  built-in tools (File Search / Code Interpreter / Bing), a LangGraph app on ACA
  behind APIM, and a Microsoft Agent Framework multi-agent system.
- **Governance wired identically for every agent** — tracing, evaluation
  (quality / safety / agentic), and red-teaming, driven by shared scripts in
  `agents/shared/` and surfaced in the same Foundry portal panes regardless of
  where the agent runs.

### The three questions it answers

| Question | How the demo answers it |
|----------|-------------------------|
| **Which agent architecture should I pick?** | Run the same inputs through all four; compare traces and eval scores. |
| **How do I bring a non-Foundry-native agent into the platform?** | Deploy LangGraph on ACA, front it with APIM as an **AI Gateway**, register it as an **external agent asset** in the Control Plane. |
| **Do Foundry's built-in capabilities behave uniformly across architectures?** | The same trace / eval / red-team scripts target every scenario. |

## Scenarios

| # | Scenario | Framework | Hosting | What it showcases |
|---|----------|-----------|---------|-------------------|
| **01** | [Prompt Agent](agents/01_prompt_agent) | Azure AI Projects Responses API + function tools | **Foundry-managed** | Simplest path — declarative instructions + tools, Foundry routes. |
| **02** | [LangGraph on ACA via AI Gateway](agents/02_langgraph_aca) | LangGraph + `azure.ai.agentserver.langgraph` | **Azure Container Apps**, fronted by **APIM AI Gateway**, registered as a Foundry **external agent asset** | BYO agent → control-plane citizen. Token quotas, semantic cache, managed-identity passthrough, end-to-end tracing. |
| **03** | [Multi-Agent (MAF Handoff)](agents/03_multi_agent) | Microsoft Agent Framework + `HandoffBuilder` | **Azure Container Apps** | Triage → specialist handoffs (flights / hotels / cars) → budget-compliance validator. Illustrates orchestration patterns. |
| **04** | [Prompt Agent with Foundry Built-in Tools](agents/04_foundry_tools_agent) | Responses API | **Foundry-managed** | File Search, Code Interpreter, Bing Grounding — out-of-the-box Foundry tools, no custom code. |

All four scenarios share the same Contoso Travel [data](data/contoso-travel/) and
the same [shared utilities](agents/shared/). Tracing, evaluation and
red-teaming are implemented **once** in `agents/shared/` and targeted at each
scenario by name.

> **Note** — Foundry *Hosted Agents* (capabilityHost-managed containers) were
> intentionally dropped from this demo. For the BYO-container story we use ACA +
> AI Gateway instead, which mirrors most real customer deployments.

## Quick Start

### 1. Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [Azure CLI (`az`)](https://learn.microsoft.com/cli/azure/install-azure-cli) | 2.60+ | Authentication, RBAC, resource discovery |
| [Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) | 1.10+ | `azd up` provisioning |
| [Bicep CLI](https://learn.microsoft.com/azure/azure-resource-manager/bicep/install) | 0.30+ | Bundled with recent `az` |
| [PowerShell](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows) | 5.1 or 7+ | `azd-prep.ps1`, `setup-env.ps1` |
| [Python](https://www.python.org/downloads/) | 3.12+ | Running demos |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | latest | Only needed if you build images locally (ACR cloud build is the default) |

Azure-side:

- Subscription with Owner or Contributor + User Access Administrator at the RG scope.
- Model quota in your region for the deployment in `main.parameters.json`
  (default: `gpt-5` GlobalStandard, 10K TPM).
- A valid **publisher email** (APIM is provisioned by default for scenario 02).

**Greenfield by default**: the Bicep creates a fresh Foundry resource, project,
Log Analytics, App Insights, ACR, Container Apps Env, Cosmos DB, Key Vault, APIM.

### 2. Infrastructure

Infra lives under [infra/](infra/) and uses **Azure Verified Modules** from the
public Bicep registry.

| Resource | AVM Module |
|----------|------------|
| Log Analytics | `avm/res/operational-insights/workspace:0.15.0` |
| Application Insights | `avm/res/insights/component:0.7.1` |
| Container Registry | `avm/res/container-registry/registry:0.12.1` |
| Foundry account | `avm/res/cognitive-services/account:0.14.2` |
| User-Assigned Identity | `avm/res/managed-identity/user-assigned-identity:0.5.0` |
| Key Vault | `avm/res/key-vault/vault:0.13.3` |
| Cosmos DB | `avm/res/document-db/database-account:0.19.0` |
| Container Apps Env | `avm/res/app/managed-environment:0.13.2` |
| Container Apps | `avm/res/app/container-app:0.22.1` |
| API Management | `avm/res/api-management/service:0.14.1` |
| Azure AI Search | `avm/res/search/search-service:0.11.1` |

Foundry project + RBAC + external-agent connection are declared inline in
[infra/modules/ai-foundry.bicep](infra/modules/ai-foundry.bicep). APIM policies
(AI Gateway) live in [infra/modules/apim-ai-gateway.bicep](infra/modules/apim-ai-gateway.bicep).

#### APIM as AI Gateway

[infra/modules/apim-ai-gateway.bicep](infra/modules/apim-ai-gateway.bicep) turns
the bare APIM instance into an AI gateway with two APIs:

| API | Source & policy | Backend dispatch |
|-----|-----------------|------------------|
| **`/openai`** | Azure OpenAI OpenAPI spec (`APIM_OPENAI_API_VERSION`). Policy ([azure-openai-api.xml](infra/modules/policies/azure-openai-api.xml)): managed-identity auth, circuit breaker, `azure-openai-token-limit` (`APIM_TOKEN_LIMIT_TPM`), `azure-openai-emit-token-metric`. | `foundry-openai` (Foundry account endpoint). |
| **`/agents`** | Typed `POST /responses`, `GET /responses/{id}`, `POST /responses/{id}/cancel` under `/agents/maf` and `/agents/langgraph`. Policy ([agents-api.xml](infra/modules/policies/agents-api.xml)): path-based backend dispatch; `validate-azure-ad-token` when `APIM_AGENTS_JWT_AUDIENCE` is set (open gateway when empty — PoC default). | ACA agent FQDN per subroute. |

Two APIM products (`openai`, `agents`) each get a subscription. With
`APIM_SECRETS_TO_KEYVAULT=true` (default) their keys land in Key Vault as
`apim-openai-sub-key` / `apim-agents-sub-key`, and the ACA apps' UAI gets
`Key Vault Secrets User` to pull them.

ACA apps are rolled onto the gateway by their own `deploy_and_register.py`
(not Bicep) to avoid a circular dependency between APIM learning the ACA FQDN
and the apps reading their subscription key. Each script sets
`AZURE_OPENAI_ENDPOINT=APIM_OPENAI_GATEWAY_URL`, injects the key from Key Vault,
and registers the agent as a Foundry project connection — no manual portal or
`az containerapp` steps.

#### Foundry IQ / Agent Knowledge (Azure AI Search)

Bicep also provisions an **Azure AI Search** service (`srch-${resourceToken}`)
and wires it into the Foundry project as a `CognitiveSearch` connection named
`search-connection`. This is the knowledge layer that backs the **Foundry IQ**
experience and any `AzureAISearchTool` used by agents.

Defaults:

- **SKU:** `standard` — easy to attach to multiple indexes during testing.
  Override via the `aiSearchSku` parameter (`free`, `basic`, `standard`,
  `standard2`, `standard3`).
- **Auth:** AAD (the Foundry project MI gets `Search Index Data Contributor`
  + `Search Service Contributor`; the deploying user gets
  `Search Index Data Contributor`). API keys remain enabled by default for
  convenience during local testing.
- **Semantic search:** standard tier enabled.
- Set `enableAiSearch=false` to skip the service entirely.

You can attach documents in the portal under **Foundry project → Knowledge**,
or programmatically create indexes via the SDK using `AZURE_AI_SEARCH_ENDPOINT`.

### 3. Deploy

```powershell
cd demo-agent-observability

# 1. Prep the azd env from your az login
.\scripts\azd-prep.ps1 -EnvName foundry-demo -Location eastus2

# 2. Provision everything
azd up

# 3. Hydrate local .env from deployment outputs
pip install -r requirements.txt
.\scripts\setup-env.ps1
```

After `azd up` the following outputs are promoted into the azd env and consumed by `setup-env.ps1`:

| azd output | `.env` key |
|------------|------------|
| `AZURE_AI_PROJECT_ENDPOINT` | `AZURE_AI_PROJECT_ENDPOINT` |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | `AZURE_AI_MODEL_DEPLOYMENT_NAME` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | `TELEMETRY_CONNECTION_STRING` |
| `AZURE_CONTAINER_REGISTRY_NAME` | `ACR_NAME` |
| `ACA_ENVIRONMENT_ID` | `ACA_ENVIRONMENT_ID` |
| `APIM_GATEWAY_URL` | `APIM_GATEWAY_URL` |
| `APIM_NAME` | `APIM_NAME` |
| `APIM_MAF_AGENT_URL` | _(registered as a Foundry project connection by `03_multi_agent/deploy_and_register.py`)_ |
| `APIM_LANGGRAPH_AGENT_URL` | _(registered as a Foundry project connection by `02_langgraph_aca/deploy_and_register.py`)_ |
| `APIM_OPENAI_GATEWAY_URL` | `APIM_OPENAI_GATEWAY_URL` |
| `APIM_AGENTS_SUBSCRIPTION_RESOURCE_ID` | _(ARM id of the `agents` subscription)_ |
| `APIM_OPENAI_SUBSCRIPTION_RESOURCE_ID` | _(ARM id of the `openai` subscription)_ |
| `APIM_OPENAI_KEY_SECRET_NAME` | _(KV secret holding the `openai` subscription key)_ |
| `APIM_AGENTS_KEY_SECRET_NAME` | _(KV secret holding the `agents` subscription key)_ |

### 4. Configuration knobs

Set any of these with `azd env set <KEY> <VALUE>` before `azd up`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `AZURE_LOCATION` | _(required)_ | Region for all resources |
| `AZURE_PRINCIPAL_ID` | _(required)_ | Object ID of the user/SP getting Foundry RBAC |
| `AZURE_PRINCIPAL_TYPE` | `User` | Set to `ServicePrincipal` in CI |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | `gpt-5` | Model deployment name |
| `APIM_PUBLISHER_EMAIL` | _(required for scenario 02)_ | APIM admin email |
| `APIM_AGENTS_JWT_AUDIENCE` | _(empty)_ | Entra app ID URI / client ID. When set, `/agents` requires a valid Entra access token with this audience. Empty leaves the gateway open (PoC default). |
| `APIM_AGENTS_JWT_TENANT_ID` | _current tenant_ | Tenant ID trusted by the `/agents` JWT validator |
| `APIM_SECRETS_TO_KEYVAULT` | `true` | Persist APIM `openai` + `agents` subscription keys as KV secrets (`apim-openai-sub-key`, `apim-agents-sub-key`). The apps UAI is granted `Key Vault Secrets User`. |
| `APIM_TOKEN_LIMIT_TPM` | `100000` | `azure-openai-token-limit` tokens-per-minute counter on `/openai` |
| `APIM_OPENAI_API_VERSION` | `2024-10-21` | OpenAPI spec version imported for `/openai` |
| `ENABLE_COMPUTE_LAYER` | `true` | Provision ACA + Cosmos + KV + APIM |
| `ENABLE_AI_SEARCH` | `true` | Provision Azure AI Search + Foundry connection |
| `AZURE_AI_SEARCH_SKU` | `standard` | Search SKU (`free`/`basic`/`standard`/`standard2`/`standard3`) |
| `LOG_ANALYTICS_RESOURCE_ID` | _(empty)_ | Reuse existing LAW |
| `APPLICATIONINSIGHTS_RESOURCE_ID` | _(empty)_ | Reuse existing App Insights |
| `AZURE_CONTAINER_REGISTRY_RESOURCE_ID` | _(empty)_ | Reuse existing ACR |

### PoC-friendly defaults (revisit before production)

- Key Vault purge protection **disabled**
- Cosmos DB **serverless**, single region
- ACR **Premium**, admin user disabled (AAD-only pulls), public access enabled (no network rules)
- All public endpoints, no private networking
- ACA consumption profile only
- APIM **StandardV2** (capacity 1)
- APIM `/agents` JWT validation **off by default** — set `APIM_AGENTS_JWT_AUDIENCE` to enable Entra token validation on the gateway
- Hosting runtimes for MAF / LangGraph (`azure-ai-agentserver-*`) are still on beta releases — pin or upgrade deliberately when GA ships

### Routing agents through the gateway

Once `azd up` finishes, the ACA apps exist but run a public placeholder image
(`mcr.microsoft.com/k8se/quickstart:latest`). Each scenario's
`deploy_and_register.py` script does the actual routing work:

1. `az acr build` the scenario image.
2. `az containerapp update` — rolls the new image, sets
   `AZURE_OPENAI_ENDPOINT=$APIM_OPENAI_GATEWAY_URL`, and mounts the APIM
   subscription key from Key Vault so the container's model calls go through
   the `/openai` gateway.
3. Creates/updates a Foundry project connection pointing at
   `$APIM_GATEWAY_URL/agents/<scenario>` with the agents subscription key.
4. Smoke-tests the agent through the APIM Responses API.

`cleanup.py` in each scenario reverses steps 2 and 3 (rolls the container
back to the placeholder image, deletes the Foundry connection). See the
[Scenario lifecycle](#scenario-lifecycle) section below.

## Running the demos

Install local deps once:

```powershell
pip install -r requirements.txt
.\scripts\setup-env.ps1
```

Every scenario exposes the same three lifecycle scripts plus a common
`scenario.py` adapter used by the shared trace / evaluate / redteam scripts.

### Scenario lifecycle

| Step | Scenarios 01 & 04 (Foundry-managed) | Scenarios 02 & 03 (ACA + APIM) |
|------|-------------------------------------|--------------------------------|
| **Bootstrap** (once) | `python -m agents.<scenario>.create_and_invoke` — creates (or version-bumps) the PromptAgent, uploads the vector store for 04, runs three demo queries. | `python -m agents.<scenario>.deploy_and_register` — ACR build → ACA revision update (APIM env vars) → Foundry project connection → smoke test. |
| **Use** (repeatable, no mutation) | `python -m agents.shared.trace \| evaluate \| redteam --scenario <n>` — `build_handle()` reuses the **latest existing version**; never creates a new one. | `python -m agents.shared.trace \| evaluate \| redteam --scenario <n>` — `build_handle()` invokes the live APIM route; `AgentHandle.version` reflects the current ACA revision name. |
| **Teardown** | `python -m agents.<scenario>.cleanup` — `agents.delete(agent_name)` cascades every version; scenario 04 also deletes the vector store and uploaded files. | `python -m agents.<scenario>.cleanup` — deletes the Foundry project connection and rolls the ACA app back to its placeholder image. The ACA app itself is left intact (it's owned by Bicep). |

> **Lifecycle discipline:** `build_handle()` is deliberately read-only for all
> scenarios. Re-running the shared trace / evaluate / redteam scripts does not
> create new Foundry agent versions, does not roll new ACA revisions, and
> does not touch the Foundry connection. Only the bootstrap scripts mutate
> server state.

### Per-scenario demo flow

#### 01 — Prompt Agent (function tools)
```powershell
python -m agents.01_prompt_agent.create_and_invoke     # create + smoke test
python -m agents.shared.trace    --scenario 01_prompt_agent
python -m agents.shared.evaluate --scenario 01_prompt_agent
python -m agents.shared.redteam  --scenario 01_prompt_agent
python -m agents.01_prompt_agent.cleanup               # teardown
```
Registers a Foundry PromptAgent (`contoso-travel-prompt-agent`) with three
`FunctionTool` declarations; the client dispatches `function_call` items against
the CSV data in `data/contoso-travel/` and feeds results back until done.

#### 02 — LangGraph on ACA via APIM AI Gateway
```powershell
python -m agents.02_langgraph_aca.deploy_and_register  # build + deploy + register
python -m agents.shared.trace    --scenario 02_langgraph_aca
python -m agents.shared.evaluate --scenario 02_langgraph_aca
python -m agents.shared.redteam  --scenario 02_langgraph_aca
python -m agents.02_langgraph_aca.cleanup              # teardown
```
Builds the LangGraph image in ACR, rolls it onto `ca-langgraph-agent` with APIM
env wiring, and creates the connection `contoso-travel-langgraph-aca-endpoint`.
Shared scripts invoke via `APIM_GATEWAY_URL/agents/langgraph`; every hop
(APIM `/agents` → ACA → APIM `/openai` → Foundry model) emits traces correlated
by `x-apim-request-id`.

#### 03 — Multi-agent (MAF `HandoffBuilder`) on ACA
```powershell
python -m agents.03_multi_agent.deploy_and_register
python -m agents.shared.trace    --scenario 03_multi_agent
python -m agents.shared.evaluate --scenario 03_multi_agent
python -m agents.shared.redteam  --scenario 03_multi_agent
python -m agents.03_multi_agent.cleanup
```
Same deploy shape as scenario 02, but the image runs a Microsoft Agent Framework
workflow: a **triage** agent hands off to **flights**, **hotels**, **cars**
specialists and a **budget validator**, served behind `/agents/maf` by
`azure-ai-agentserver-agentframework`. Traces show the triage span, each
specialist invocation, the handoff edges, and the per-turn APIM `/openai` call.

#### 04 — Prompt Agent with Foundry built-in tools
```powershell
python -m agents.04_foundry_tools_agent.create_and_invoke
python -m agents.shared.trace    --scenario 04_foundry_tools_agent
python -m agents.shared.evaluate --scenario 04_foundry_tools_agent
python -m agents.shared.redteam  --scenario 04_foundry_tools_agent
python -m agents.04_foundry_tools_agent.cleanup
```
Provisions a vector store from `agents/04_foundry_tools_agent/data/*.md` (id
cached in `.vector_store_id`) and registers a PromptAgent with `FileSearchTool`
+ `CodeInterpreterTool`, plus `BingGroundingTool` when
`BING_GROUNDING_CONNECTION_ID` is set. All tool execution is server-side.

## Project structure

```
demo-agent-observability/
├── README.md                          # This file
├── azure.yaml                         # azd service bindings
├── requirements.txt                   # Python dependencies
├── .env.sample
│
├── data/contoso-travel/               # Shared sample data (flights/hotels/cars CSVs)
├── scripts/                           # azd-prep.ps1, setup-env.ps1
├── infra/
│   ├── main.bicep
│   ├── main.parameters.json
│   └── modules/
│       ├── ai-foundry.bicep           # Foundry account + project + RBAC
│       ├── compute-layer.bicep        # UAI + KV + Cosmos + ACA env + ACA apps + APIM
│       └── apim-ai-gateway.bicep      # AI Gateway policies (/openai, /agents)
│
└── agents/
    ├── shared/                        # Shared across all scenarios
    │   ├── config.py                  # Clients + env
    │   ├── tools.py                   # Travel search functions (scenario 01)
    │   ├── aca_connection.py          # APIM client, ACA rollback, connection delete (02/03)
    │   ├── eval_utils.py              # Quality / safety / agentic / redteam helpers
    │   ├── registry.py                # Scenario → AgentHandle lookup
    │   ├── trace.py                   # Unified tracing entrypoint
    │   ├── evaluate.py                # Unified evaluation entrypoint
    │   └── redteam.py                 # Unified red-team entrypoint
    │
    ├── 01_prompt_agent/               # Foundry-managed prompt agent
    │   ├── agent_def.py               # Tool schemas + run_tool_loop
    │   ├── create_and_invoke.py       # Bootstrap (bumps version)
    │   ├── scenario.py                # Read-only adapter (latest version)
    │   └── cleanup.py
    │
    ├── 02_langgraph_aca/              # LangGraph on ACA + APIM AI Gateway
    │   ├── src/                       # Container image (agent_app.py + Dockerfile)
    │   ├── deploy_and_register.py     # ACR build + ACA update + Foundry connection
    │   ├── scenario.py                # Read-only adapter (APIM client)
    │   └── cleanup.py                 # Delete connection + rollback ACA to placeholder
    │
    ├── 03_multi_agent/                # MAF HandoffBuilder on ACA + APIM AI Gateway
    │   ├── src/                       # Container image (agent_app.py + Dockerfile)
    │   ├── deploy_and_register.py
    │   ├── scenario.py
    │   └── cleanup.py
    │
    └── 04_foundry_tools_agent/        # Prompt agent with built-in Foundry tools
        ├── agent_def.py               # FileSearch/CodeInterpreter/Bing + vector store
        ├── data/                      # Policy docs uploaded to the vector store
        ├── create_and_invoke.py
        ├── scenario.py
        └── cleanup.py                 # Delete agent + vector store + uploaded files
```

## Demo narrative

### Act 1 — Pick your architecture
Four agents, one scenario. Same inputs, same outputs, radically different
implementations. Show each running locally and in Foundry.

### Act 2 — BYO agent becomes a first-class asset
Walk through the ACA + AI Gateway flow for scenario 02: container image → ACA
revision → APIM route with token-quota/semantic-cache/MI policies → external
agent connection in the Foundry Control Plane. The agent appears in the
portal's Agents catalog next to the native ones.

### Act 3 — Unified observability
All four agents emit spans to the same App Insights / Foundry Tracing view.
Compare span depth: API only (prompt agent) → API + tool (built-in tools) →
API + graph nodes (LangGraph) → API + handoff + specialist spans (multi-agent).

### Act 4 — Agent-agnostic evaluation and red-teaming
Same `evaluate --scenario <n>` and `redteam --scenario <n>` against all four.
Compare quality, safety, and vulnerability profiles side-by-side in the Foundry
portal.

#### How `evaluate` works across all 4 scenarios

The shared `evaluate` script uses **local generation + remote judges**:

1. For every row of `data/contoso-travel/evaluation_data.jsonl`, it calls
   `handle.invoke(query)` inside an OTel span tagged with the eval run name,
   scenario, agent name/version, and query index. The agent's full trace
   (tool calls, graph nodes, handoff edges, model hops) is exported to App
   Insights via `AIProjectInstrumentor`.
2. The pre-generated `{query, response, context, ground_truth}` items are
   submitted to Foundry evals via a `jsonl` data source. The Foundry judges
   (fluency / coherence / task adherence / groundedness / relevance /
   violence / hate-unfairness / self-harm) score the live responses.

This unifies the code path across all four scenarios — including scenarios 02
and 03 whose asset identity is a Foundry project connection and therefore
can't be used as an `azure_ai_agent` eval target.

**Trace ↔ eval correlation in the portal:**
- **Evaluations pane** — shows scores + inputs/outputs per row.
- **Tracing pane** — filter by `evaluation.run_name` to see the full agent
  trace that produced each response, matched row-by-row with the eval run.

#### Red-teaming scope

The server-side red-team orchestrator (`redteam` script) targets Foundry
PromptAgents via `AzureAIAgentTarget(name, version)` — so it works directly
for scenarios **01** and **04**. For scenarios **02** and **03** it prints
a skip message: the connection-backed target type is not yet supported by
the orchestrator. The recommended extension is
[`azure-ai-evaluation.red_team.RedTeam`](https://learn.microsoft.com/azure/foundry/concepts/ai-red-teaming-agent)
with `handle.invoke` as a callback target.

## Resources

| Resource | Link |
|----------|------|
| Foundry Control Plane | [Overview](https://learn.microsoft.com/azure/foundry/control-plane/overview) |
| External agent assets | [Guide](https://learn.microsoft.com/azure/foundry/agents/external-agents) |
| APIM AI Gateway | [Guide](https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities) |
| Agent Tracing | [Concepts](https://learn.microsoft.com/azure/foundry/observability/concepts/trace-agent-concept) |
| Built-in Evaluators | [Reference](https://learn.microsoft.com/azure/foundry/concepts/built-in-evaluators) |
| Red Teaming | [Guide](https://learn.microsoft.com/azure/foundry/concepts/ai-red-teaming-agent) |
| Microsoft Agent Framework | [GitHub](https://github.com/microsoft/agent-framework) |
| LangGraph server adapter | [SDK](https://pypi.org/project/azure-ai-agentserver-langgraph/) |
