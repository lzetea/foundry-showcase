# Microsoft Foundry — End-to-End Showcase

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Bicep](https://img.shields.io/badge/IaC-Bicep%20%2B%20AVM-0078d4.svg)](infra/)
[![CI](https://github.com/lzetea/foundry-showcase/actions/workflows/ci.yml/badge.svg)](https://github.com/lzetea/foundry-showcase/actions/workflows/ci.yml)

A single Contoso Travel scenario implemented as four progressively richer agent
architectures, all unified under the **Microsoft Foundry Control Plane** — stand
up a Foundry environment in one `azd up` and explore its **agentic** (Prompt
Agents, multi-agent, BYO via AI Gateway, Foundry-hosted) and **governance**
(tracing, evals, red-teaming) capabilities end-to-end.

> **Status — personal demo repo.** PoC defaults throughout (no private
> networking, open APIM `/agents` gateway, Key Vault purge protection off,
> serverless single-region Cosmos, beta Foundry SDK pins). Not production-ready
> as shipped — see [PoC-friendly defaults](#poc-friendly-defaults-revisit-before-production)
> for what to harden first.

## Contents

- [TL;DR](#tldr)
- [What you get](#what-you-get)
- [Scenarios](#scenarios)
- [Quick Start](#quick-start)
  - [Prerequisites](#1-prerequisites)
  - [Infrastructure](#2-infrastructure)
  - [Deploy](#3-deploy)
  - [Configuration knobs](#4-configuration-knobs)
  - [PoC-friendly defaults](#poc-friendly-defaults-revisit-before-production)
- [Running the demos](#running-the-demos)
  - [Scenario lifecycle](#scenario-lifecycle)
  - [Per-scenario demo flow](#per-scenario-demo-flow)
- [Project structure](#project-structure)
- [Demo narrative](#demo-narrative)
- [Resources](#resources)

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

- **A complete Foundry sandbox** (Bicep + Azure Verified Modules) — a Foundry
  account & project with a model deployment, plus the supporting layers:
  observability (Application Insights + Log Analytics), an APIM AI Gateway, and
  compute (Container Apps, ACR, Key Vault, Cosmos DB, Azure AI Search). RBAC is
  pre-wired for your user and the agent runtimes.
- **Four reference agents** on one Contoso Travel scenario, running
  side-by-side so you compare architectures, not just frameworks — from a
  Foundry-managed Prompt Agent to a Foundry-hosted container (full list in
  [Scenarios](#scenarios)).
- **Governance wired identically for every agent** — tracing, evaluation
  (quality / safety / agentic), and red-teaming, driven by shared scripts in
  `agents/shared/` and surfaced in the same Foundry portal panes regardless of
  where the agent runs.

### The three questions it answers

| Question | How the demo answers it |
|----------|-------------------------|
| **Which agent architecture should I pick?** | Run the same inputs through all four; compare traces and eval scores. |
| **How do I bring a non-Foundry-native agent into the platform?** | Deploy LangGraph on ACA, front it with APIM as an **AI Gateway**, register it as a Foundry **project connection** in the Control Plane. |
| **Do Foundry's built-in capabilities behave uniformly across architectures?** | The same trace / eval / red-team scripts target every scenario. |

## Scenarios

| # | Scenario | Framework | Hosting | What it showcases |
|---|----------|-----------|---------|-------------------|
| **01** | [Prompt Agent](agents/01_prompt_agent) | Azure AI Projects Responses API + function tools | **Foundry-managed** | Simplest path — declarative instructions + tools, Foundry routes. |
| **02** | [LangGraph on ACA via AI Gateway](agents/02_langgraph_aca) | LangGraph + `azure.ai.agentserver.langgraph` | **Azure Container Apps**, fronted by **APIM AI Gateway**, registered as a Foundry **project connection** | BYO agent → control-plane citizen. Token quotas, semantic cache, managed-identity passthrough, end-to-end tracing. |
| **03** | [Multi-Agent (MAF)](agents/03_multi_agent) | Microsoft Agent Framework (agents-as-tools) | **Azure Container Apps** | A triage agent orchestrates flights / hotels / cars specialists + a budget-compliance validator. Illustrates multi-agent orchestration. |
| **04** | [Foundry Hosted Agent](agents/04_hosted_agent) | Microsoft Agent Framework + `agent-framework-foundry-hosting` | **Foundry-hosted** (managed container + Entra agent identity) | Same containerized agent code as 02/03, but **Foundry builds and runs it** — no ACA, no APIM, no keys. The "vs bring-your-own-infrastructure" contrast. |

All four scenarios share the same Contoso Travel [data](data/contoso-travel/) and
the same [shared utilities](agents/shared/). Tracing, evaluation and
red-teaming are implemented **once** in `agents/shared/` and targeted at each
scenario by name.

## Quick Start

### 1. Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [Azure CLI (`az`)](https://learn.microsoft.com/cli/azure/install-azure-cli) | 2.60+ | Authentication, RBAC, resource discovery |
| [Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) | 1.25+ | `azd up` provisioning; `azd ai agent` for scenario 04 (needs the `azure.ai.agents` extension) |
| [Bicep CLI](https://learn.microsoft.com/azure/azure-resource-manager/bicep/install) | 0.30+ | Bundled with recent `az` |
| [PowerShell](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows) | 5.1 or 7+ | `azd-prep.ps1`, `setup-env.ps1` |
| [Python](https://www.python.org/downloads/) | 3.12+ | Running demos |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | latest | Only needed if you build images locally (ACR cloud build is the default) |

Azure-side:

- Subscription with Owner or Contributor + User Access Administrator at the RG scope.
- Model quota in your region for the deployment in `main.parameters.json`
  (default: `gpt-5` GlobalStandard, 10K TPM).
- A valid **publisher email** (APIM is provisioned by default for scenario 02).

**Greenfield by default**: the Bicep provisions everything fresh. To reuse
existing resources, point the `*_RESOURCE_ID` knobs below at your Log Analytics /
App Insights / ACR.

### 2. Infrastructure

Infra lives under [infra/](infra/) and is built almost entirely from **[Azure
Verified Modules](https://aka.ms/avm)** — see [infra/main.bicep](infra/main.bicep)
for the full set and pinned module versions. The Foundry project and its RBAC are
declared inline in
[infra/modules/ai-foundry.bicep](infra/modules/ai-foundry.bicep); the APIM AI
Gateway policies live in
[infra/modules/apim-ai-gateway.bicep](infra/modules/apim-ai-gateway.bicep).

#### APIM as AI Gateway

[infra/modules/apim-ai-gateway.bicep](infra/modules/apim-ai-gateway.bicep) turns
the APIM instance into an AI gateway with two APIs: **`/openai`** (managed-identity
auth, circuit breaker, token-limit + token-metric policies in front of the Foundry
model) and **`/agents`** (path-based dispatch to the ACA agents under
`/agents/maf` and `/agents/langgraph`, with optional Entra token validation via
`APIM_AGENTS_JWT_AUDIENCE`). Each API's subscription key is persisted to Key Vault;
the ACA apps read theirs via a `Key Vault Secrets User` grant. The apps are rolled
onto the gateway by their own `deploy_and_register.py` (not Bicep) to avoid a
chicken-and-egg between APIM learning the ACA FQDN and the apps reading their key.

#### Foundry IQ / Agent Knowledge (Azure AI Search)

Bicep also provisions an **Azure AI Search** service and wires it into the
Foundry project as a `CognitiveSearch` connection (`search-connection`) — the
knowledge layer behind **Foundry IQ** and any `AzureAISearchTool`. It defaults to
the `standard` SKU with AAD auth and semantic search on; attach documents under
**Foundry project → Knowledge** or via the SDK (`AZURE_AI_SEARCH_ENDPOINT`). Set
`enableAiSearch=false` to skip it.

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

`setup-env.ps1` promotes the `azd up` outputs into `.env` — project endpoint,
model deployment, the App Insights connection string (as
`TELEMETRY_CONNECTION_STRING`), ACR, the ACA environment, and the APIM gateway
URLs / subscription-key secret names. Scenarios 02–03 register their APIM agent
URLs as Foundry project connections inside `deploy_and_register.py`. See
[DEPLOY_AGENT.md](DEPLOY_AGENT.md) Phase 5 for the required-outputs checklist.

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

With `.env` hydrated (the [Deploy](#3-deploy) step above), every scenario exposes
the same three lifecycle scripts plus a common `scenario.py` adapter used by the
shared trace / evaluate / redteam scripts.

### Scenario lifecycle

| Step | Scenario 01 (Foundry-managed) | Scenarios 02 & 03 (ACA + APIM) |
|------|-------------------------------|--------------------------------|
| **Bootstrap** (once) | `python -m agents.01_prompt_agent.create_and_invoke` — creates (or version-bumps) the PromptAgent and runs three demo queries. | `python -m agents.<scenario>.deploy_and_register` — ACR build → ACA revision update (APIM env vars) → Foundry project connection → smoke test. |
| **Use** (repeatable, no mutation) | `python -m agents.shared.trace \| evaluate \| redteam --scenario <n>` — `build_handle()` reuses the **latest existing version**; never creates a new one. | `python -m agents.shared.trace \| evaluate \| redteam --scenario <n>` — `build_handle()` invokes the live APIM route; `AgentHandle.version` reflects the current ACA revision name. |
| **Teardown** | `python -m agents.01_prompt_agent.cleanup` — `agents.delete(agent_name)` cascades every version. | `python -m agents.<scenario>.cleanup` — deletes the Foundry project connection and rolls the ACA app back to its placeholder image. The ACA app itself is left intact (it's owned by Bicep). |

> **Scenario 04 (Foundry-hosted)** doesn't use these scripts — Foundry builds and
> versions it. Deploy with `azd deploy contoso-travel-hosted` (see the
> [04 section](#04--foundry-hosted-agent) and DEPLOY_AGENT.md Phase 7b); the
> shared trace / evaluate / redteam scripts still target it read-only.

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

#### 03 — Multi-agent (MAF, agents-as-tools) on ACA
```powershell
python -m agents.03_multi_agent.deploy_and_register
python -m agents.shared.trace    --scenario 03_multi_agent
python -m agents.shared.evaluate --scenario 03_multi_agent
python -m agents.shared.redteam  --scenario 03_multi_agent
python -m agents.03_multi_agent.cleanup
```
Same deploy shape as scenario 02, but the image runs a Microsoft Agent Framework
system: a **triage** agent calls **flights**, **hotels**, **cars** specialists
and a **budget validator** as tools, served behind `/agents/maf` by
`azure-ai-agentserver-agentframework`. Traces show the triage span, each nested
specialist invocation, and the per-turn APIM `/openai` call.

#### 04 — Foundry hosted agent
```powershell
azd deploy contoso-travel-hosted
azd ai agent invoke contoso-travel-hosted '{"input": "Business-class Seattle to Paris and a 4-star hotel with a gym."}'
python -m agents.shared.trace    --scenario 04_hosted_agent
python -m agents.shared.evaluate --scenario 04_hosted_agent
python -m agents.shared.redteam  --scenario 04_hosted_agent
```
The same containerized agent code as 02/03, but **Foundry hosts it**: `azd deploy`
remote-builds the image in ACR and publishes a versioned hosted agent that reaches
the model via its managed identity — no APIM gateway, no keys. It's also wired for
the **Agent Optimizer** (`azd ai agent eval generate` → `azd ai agent optimize`) —
see [agents/04_hosted_agent](agents/04_hosted_agent).

## Project structure

```
demo-agent-observability/
├── README.md                          # This file
├── azure.yaml                         # azd service bindings
├── requirements.txt                   # Python dependencies
├── .env.sample
│
├── data/contoso-travel/               # Shared sample data (flights/hotels/cars CSVs)
├── scripts/                           # azd-prep.ps1, setup-env.ps1, load-test.py (seed traces)
├── infra/
│   ├── main.bicep
│   ├── main.parameters.json
│   └── modules/
│       ├── ai-foundry.bicep           # Foundry account + project + RBAC
│       ├── ai-search.bicep            # Azure AI Search + Foundry connection
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
    ├── 03_multi_agent/                # MAF multi-agent (agents-as-tools) on ACA + APIM AI Gateway
    │   ├── src/                       # Container image (agent_app.py + Dockerfile)
    │   ├── deploy_and_register.py
    │   ├── scenario.py
    │   └── cleanup.py
    │
    └── 04_hosted_agent/               # Foundry-hosted agent (managed container)
        ├── agent/                     # Deployed unit: main.py, Dockerfile, agent.yaml
        │   ├── main.py                # ResponsesHostServer + MAF agent + function tools (load_config)
        │   ├── data/                  # Contoso flights/hotels/cars CSVs baked into the image
        │   ├── instructions/          # Concierge system prompt (seeds the optimizer baseline)
        │   └── .agent_configs/        # Agent Optimizer baseline (metadata.yaml + instructions.md)
        ├── eval.yaml                  # Eval suite (azd ai agent eval generate)
        └── scenario.py                # Harness handle (agent Responses endpoint + bearer token)
```

## Demo narrative

1. **Pick your architecture** — four agents, one Contoso Travel scenario, same
   inputs and outputs, radically different implementations. Run each and compare.
2. **BYO agent becomes a first-class citizen** — scenario 02's container → ACA
   revision → APIM route (token-quota / semantic-cache / MI policies) → a Foundry
   **project connection**, discoverable in the Control Plane with the same RBAC,
   tracing, and eval surface as the native agents.
3. **Unified observability** — all four agents emit spans to the same App
   Insights / Foundry Tracing view. Span depth grows with the architecture:
   function-tool calls (prompt agent) → graph nodes (LangGraph) → nested
   specialist spans (multi-agent) → the managed hosted runtime's server span
   (hosted agent). Seed a batch of traces per scenario with
   `python scripts/load-test.py --scenario <n>` (see
   [DEPLOY_AGENT.md](DEPLOY_AGENT.md) Phase 8 for the telemetry env note).
4. **Agent-agnostic evaluation & red-teaming** — the same `evaluate` and
   `redteam --scenario <n>` run against all four, compared side-by-side in the
   portal.

**How `evaluate` works:** for each row of `evaluation_data.jsonl` it calls
`handle.invoke(query)` inside an OTel span (exported to App Insights via
`AIProjectInstrumentor`), then submits the `{query, response, context,
ground_truth}` items to Foundry judges (quality + safety evaluators). This single
code path works for all four scenarios — including 02/03, whose connection-backed
identity can't be an `azure_ai_agent` eval target. In the portal, filter the
Tracing pane by `evaluation.run_name` to line each score up with the trace that
produced it.

**Red-teaming scope:** the server-side orchestrator targets Foundry-registered
agent assets via `AzureAIAgentTarget(name, version)`, so it runs directly for
scenarios **01** and **04**; **02/03** print a skip (connection-backed targets aren't supported
yet — extend with [`azure-ai-evaluation.red_team.RedTeam`](https://learn.microsoft.com/azure/foundry/concepts/ai-red-teaming-agent)
using `handle.invoke` as the callback target).

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
