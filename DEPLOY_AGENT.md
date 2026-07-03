# Agent Deployment Runbook

> **Audience: an AI coding agent** assisting a human operator to deploy this
> solution. This file is a deterministic runbook, not narrative docs. Execute
> phases in order. Do not skip verification gates. If a gate fails, stop and
> follow the failure branch — do not proceed to the next phase.
>
> Human-facing conceptual docs live in [README.md](README.md). Read it only if
> the operator asks "why", not "how".

---

## Operating rules

1. **Never run `azd down`** on this environment without explicit operator
   confirmation. `azd down` deletes the entire resource group, including
   resources it did not create.
2. **Confirm before any destructive or irreversible action**: deleting
   resources, `azd down`, role-assignment removal, purging Key Vault.
3. **Run one command at a time.** Wait for exit, inspect output, then proceed.
4. **Treat secrets as opaque.** Do not echo Key Vault secret values, subscription
   keys, or tokens to the operator. Reference them by name only.
5. **Stop at the first failed gate.** Report the exact error and the failure
   branch you are taking. Ask the operator before improvising a fix that
   changes infrastructure.
6. All paths below are relative to `demo-agent-observability/`. `cd` there first.

---

## Inputs to collect from the operator

Ask for these up front. Do not guess.

| Input | Required | Default if omitted | Notes |
|-------|----------|--------------------|-------|
| Azure region | yes | — | Must have model quota (see Phase 1). |
| azd env name | no | `foundry-demo` | Lowercase, no spaces. |
| Model deployment name | no | `gpt-5` | Must exist as quota in the region. |
| APIM publisher email | yes if compute layer on | — | A real mailbox; APIM sends notifications. |
| Deploy compute layer (ACA + APIM + Cosmos)? | no | yes | Set `ENABLE_COMPUTE_LAYER=false` to skip scenarios 02/03. |
| Reuse existing LAW / App Insights / ACR? | no | no (greenfield) | If yes, collect the resource IDs. |

---

## Phase 0 — Toolchain preflight

Run each check. All must pass before continuing.

```powershell
az version                 # expect 2.60 or later
azd version                # expect 1.25 or later (scenario 04 uses `azd ai agent`)
az bicep version           # expect 0.30 or later
python --version           # expect 3.12 or later
az account show            # expect a JSON account object (proves az login)
```

**Gate 0:**
- Any tool missing → install it from the link in [README.md](README.md#1-prerequisites), then re-run.
- `az account show` errors → run `az login --use-device-code`, then re-check.
- Wrong subscription → `az account set --subscription <id>`.

---

## Phase 1 — Quota & permission check

```powershell
# Confirm the operator has rights to assign roles (need Owner OR
# Contributor + User Access Administrator at the target scope).
az role assignment list --assignee <operator-object-id> --query "[].roleDefinitionName" -o tsv

# Confirm model quota in the chosen region for the chosen model.
az cognitiveservices usage list --location <region> -o table
```

**Gate 1:**
- Missing role → tell the operator exactly which role they lack. Do not proceed.
- Zero quota for the model in the region → propose a different region OR a
  different model, and update the chosen inputs. Do not proceed with zero quota.

---

## Phase 2 — Environment prep

```powershell
cd demo-agent-observability
.\scripts\azd-prep.ps1 -EnvName <env-name> -Location <region>
```

This script verifies login, initializes the azd env, and sets
`AZURE_LOCATION`, `AZURE_PRINCIPAL_ID`, `AZURE_PRINCIPAL_TYPE`.

Then set any non-default knobs the operator chose:

```powershell
azd env set APIM_PUBLISHER_EMAIL <email>          # required if compute layer on
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME <name> # only if not gpt-5
azd env set ENABLE_COMPUTE_LAYER false            # only if skipping ACA/APIM
azd env set AZURE_AI_SEARCH_SKU <sku>             # only if not standard
# Reuse existing resources (optional):
azd env set LOG_ANALYTICS_RESOURCE_ID <id>
azd env set APPLICATIONINSIGHTS_RESOURCE_ID <id>
azd env set AZURE_CONTAINER_REGISTRY_RESOURCE_ID <id>
```

**Gate 2:** `azd env get-values` must show `AZURE_LOCATION`,
`AZURE_PRINCIPAL_ID`, and (if compute layer on) `APIM_PUBLISHER_EMAIL`
populated. If any required value is empty, set it before continuing.

---

## Phase 3 — Validate infrastructure (no-op dry run)

```powershell
az bicep build --file infra\main.bicep      # expect exit 0, no BCP errors
azd provision --preview                       # review the change set
```

**Gate 3:**
- Bicep build emits `BCP` errors → stop, report them, do not provision.
- `--preview` shows deletions of resources the operator wants to keep → stop and
  confirm with the operator before proceeding.

---

## Phase 4 — Provision

```powershell
azd up
```

This provisions: Foundry account + project, model deployment, Log Analytics,
App Insights, ACR, Key Vault, Azure AI Search, and (if enabled) Cosmos DB,
ACA environment + apps, and APIM AI Gateway.

**Expected duration:** APIM dominates; allow 30–45 min when the compute layer
is on. Do not interrupt. Do not poll in a tight loop — wait for the command to
return.

**Gate 4:**
- Quota error → return to Gate 1.
- APIM publisher email error → set `APIM_PUBLISHER_EMAIL` and re-run `azd up`.
- Role-assignment `AuthorizationFailed` → operator lacks User Access
  Administrator; stop and report.
- Transient ARM error → re-run `azd up` once (provisioning is idempotent).
  If it fails twice the same way, stop and report.

---

## Phase 5 — Hydrate local config & verify

```powershell
pip install -r requirements.txt
.\scripts\setup-env.ps1                       # writes .env from azd outputs
azd env get-values                            # confirm outputs are present
```

**Gate 5 — required outputs present:**
- `AZURE_AI_PROJECT_ENDPOINT`
- `AZURE_AI_MODEL_DEPLOYMENT_NAME`
- `APPLICATIONINSIGHTS_CONNECTION_STRING`
- `AZURE_AI_SEARCH_ENDPOINT`
- If compute layer on: `APIM_GATEWAY_URL`, `APIM_OPENAI_GATEWAY_URL`,
  `AZURE_CONTAINER_REGISTRY_NAME`, `ACA_ENVIRONMENT_ID`

Any missing → re-run `setup-env.ps1`; if still missing, the corresponding
module failed in Phase 4 — inspect `azd` logs.

---

## Phase 6 — Smoke test (prove the platform works)

Run the simplest Foundry-managed scenario first; it has no ACA/APIM dependency.

```powershell
python -m agents.01_prompt_agent.create_and_invoke
```

**Gate 6:** Expect three demo queries to return `output_text`. On auth errors,
confirm `AZURE_AI_PROJECT_ENDPOINT` and that RBAC propagation has completed
(can lag a few minutes after `azd up`); wait and retry once.

---

## Phase 7 — Route the BYO agents (only if compute layer is on)

Each ACA scenario starts on a placeholder image until its register script runs.

```powershell
python -m agents.02_langgraph_aca.deploy_and_register
python -m agents.03_multi_agent.deploy_and_register
```

Each script: builds the image in ACR → rolls the ACA revision with APIM env
wiring → creates a Foundry project connection → smoke-tests via the APIM
Responses API.

**Gate 7:**
- ACR build failure → report the build log; do not retry blindly.
- Smoke test 401/403 at the gateway → the agents subscription key wasn't read
  from Key Vault; confirm the apps UAI has `Key Vault Secrets User` and retry.
- A failed scenario does not block the others; report which succeeded.

---

## Phase 7b — Deploy the Foundry-hosted agent (scenario 04)

Scenario 04 is built and run by Foundry itself — no ACA or APIM. It uses the
`azure.ai.agents` azd extension and the env values hydrated in Phase 5.

```powershell
azd extension install azure.ai.agents        # once, if not already installed
azd deploy contoso-travel-hosted             # remote-builds the image in ACR, publishes a hosted agent version
azd ai agent invoke contoso-travel-hosted '{"input": "Business-class Seattle to Paris and a 4-star hotel with a gym."}'
```

**Gate 7b:**
- `azd deploy` must end with `Done` plus a portal + Responses endpoint URL, and
  the invoke must return grounded Contoso flight/hotel data.
- Build failure → inspect the ACR remote-build log; do not retry blindly.
- Invoke auth error → confirm the agent's managed identity has **Azure AI User**
  on the Foundry account; RBAC propagation can lag a few minutes, retry once.

---

## Phase 8 — Optional: governance surfaces

For any deployed scenario `<n>` (`01_prompt_agent`, `02_langgraph_aca`,
`03_multi_agent`, `04_hosted_agent`):

```powershell
python -m agents.shared.trace    --scenario <n>
python -m agents.shared.evaluate --scenario <n>
python -m agents.shared.redteam  --scenario <n>   # 01 & 04 only; 02/03 print a skip
```

These are read-only against server state and safe to re-run.

**Seed traces for observability** (optional) with the load generator. It exports
spans only when `TELEMETRY_CONNECTION_STRING` is set in the **shell** (the script
reads `os.environ` before `.env` is loaded), so set it from `.env` first:

```powershell
$env:TELEMETRY_CONNECTION_STRING = ((Get-Content .env | Select-String '^TELEMETRY_CONNECTION_STRING=' | Select-Object -First 1).Line -replace '^TELEMETRY_CONNECTION_STRING=','')
python scripts/load-test.py --scenario 01_prompt_agent --total 30
```

**Evaluate & optimize the hosted agent** (scenario 04 only): `main.py` loads its
prompt/model from `.agent_configs/baseline/` so Foundry's Agent Optimizer can tune
them. Do not apply a candidate without operator review.

```powershell
azd ai agent eval generate                                         # eval.yaml + baseline
azd ai agent optimize --optimize-model gpt-5 --eval-model gpt-5.4-nano
# after review:
azd ai agent optimize apply --candidate <id>; azd deploy contoso-travel-hosted
```

---

## Teardown (destructive — confirm first)

**Per-scenario rollback** (reverses Phase 7, leaves infra intact):

```powershell
python -m agents.02_langgraph_aca.cleanup
python -m agents.03_multi_agent.cleanup
python -m agents.01_prompt_agent.cleanup
# 04 hosted agent: delete the agent version in the Foundry portal, or run
# `azd down` to tear down the whole environment (destructive).
```

**Full environment teardown** — destroys the entire resource group:

```powershell
azd down --purge        # REQUIRES explicit operator confirmation
```

> ⚠️ `azd down` deletes everything in the resource group, not only what azd
> created. If this env points at a shared/pre-existing RG, do **not** run it —
> delete the `.azure/` folder instead to detach azd without touching Azure.

---

## Quick failure index

| Symptom | Phase | Action |
|---------|-------|--------|
| `az`/`azd` not found | 0 | Install, re-run Phase 0. |
| Not logged in | 0 | `az login --use-device-code`. |
| `AuthorizationFailed` on role assignment | 4 | Operator needs User Access Administrator. Stop. |
| Quota = 0 for model | 1/4 | Change region or model. Stop. |
| APIM publisher email error | 4 | `azd env set APIM_PUBLISHER_EMAIL <email>`, re-run `azd up`. |
| Missing azd output | 5 | Re-run `setup-env.ps1`; if persists, module failed in Phase 4. |
| Agent auth error on first invoke | 6 | RBAC propagation lag; wait, retry once. |
| Gateway 401/403 | 7 | UAI missing `Key Vault Secrets User`; verify, retry. |
