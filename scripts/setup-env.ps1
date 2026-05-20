# ============================================================
#  Foundry Control Plane — Agent Observability Demo
#  Environment Setup Script (PowerShell)
# ============================================================
#  This script:
#    1. Checks Azure CLI login status (prompts az login if needed)
#    2. Creates a .env file from .env.sample (if it doesn't exist)
#    3. Auto-populates values it can discover via Azure CLI
#    4. Reports which values still need manual entry
#
#  Usage:
#    .\setup-env.ps1
#
#  Prerequisites:
#    - Azure CLI (az) installed
#    - A Microsoft Foundry project already created
# ============================================================

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $ScriptDir ".env"
$SampleFile = Join-Path $ScriptDir ".env.sample"

# ── Helper: Set a value in .env only if currently empty ──
function Set-EnvIfEmpty {
    param(
        [string]$Key,
        [string]$Value
    )

    $content = Get-Content $EnvFile -Raw
    $pattern = "(?m)^${Key}=(.*)$"

    if ($content -notmatch $pattern) {
        # Key doesn't exist — append it (ensure trailing newline first)
        if ($content.Length -gt 0 -and $content[-1] -ne "`n") {
            Add-Content -Path $EnvFile -Value ""
        }
        Add-Content -Path $EnvFile -Value "${Key}="
        $content = Get-Content $EnvFile -Raw
    }

    $match = [regex]::Match($content, $pattern)
    $currentValue = $match.Groups[1].Value.Trim().Trim('"')

    if ([string]::IsNullOrEmpty($currentValue) -and -not [string]::IsNullOrEmpty($Value)) {
        $content = $content -replace $pattern, "${Key}=${Value}"
        Set-Content -Path $EnvFile -Value $content.TrimEnd()
        $display = if ($Value.Length -gt 50) { $Value.Substring(0, 50) + "..." } else { $Value }
        Write-Host "  [OK] ${Key} -> ${display}" -ForegroundColor Green
        return $true
    }
    elseif (-not [string]::IsNullOrEmpty($currentValue)) {
        Write-Host "  [OK] ${Key} already set" -ForegroundColor Green
        return $true
    }
    return $false
}

# ════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "   Foundry Control Plane - Agent Observability Demo Setup" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""

# ────────────────────────────────────────────────────────────
#  Fast path: if an azd environment exists with outputs from
#  a successful `azd up`, hydrate .env directly from them and
#  skip the Azure CLI discovery path entirely.
# ────────────────────────────────────────────────────────────
$azdExists = Get-Command azd -ErrorAction SilentlyContinue
if ($azdExists) {
    $azdValues = $null
    try {
        $azdValuesRaw = azd env get-values 2>$null
        if ($LASTEXITCODE -eq 0 -and $azdValuesRaw) {
            $azdValues = @{}
            $rx = [regex]'^\s*([A-Z0-9_]+)\s*=\s*"?([^"]*)"?\s*$'
            foreach ($line in ($azdValuesRaw -split "`n")) {
                $m = $rx.Match($line)
                if ($m.Success) {
                    $azdValues[$m.Groups[1].Value] = $m.Groups[2].Value
                }
            }
        }
    } catch { }

    if ($azdValues -and $azdValues.ContainsKey("AZURE_AI_PROJECT_ENDPOINT") -and -not [string]::IsNullOrWhiteSpace($azdValues["AZURE_AI_PROJECT_ENDPOINT"])) {
        Write-Host "[azd] Detected azd environment with deployment outputs - hydrating .env from azd..." -ForegroundColor Blue

        if (-not (Test-Path $SampleFile)) {
            Write-Host "  [X] .env.sample not found at: ${SampleFile}" -ForegroundColor Red
            exit 1
        }
        if (-not (Test-Path $EnvFile)) {
            Copy-Item $SampleFile $EnvFile
            Write-Host "  [OK] Created .env from .env.sample" -ForegroundColor Green
        }

        # Map azd output names -> .env keys consumed by the Python agents.
        $map = @{
            "AZURE_AI_PROJECT_ENDPOINT"             = "AZURE_AI_PROJECT_ENDPOINT"
            "AZURE_AI_MODEL_DEPLOYMENT_NAME"        = "AZURE_AI_MODEL_DEPLOYMENT_NAME"
            "APPLICATIONINSIGHTS_CONNECTION_STRING" = "TELEMETRY_CONNECTION_STRING"
            "AZURE_CONTAINER_REGISTRY_NAME"         = "ACR_NAME"
            "AZURE_SUBSCRIPTION_ID"                 = "AZURE_SUBSCRIPTION_ID"
            "AZURE_RESOURCE_GROUP"                  = "AZURE_RESOURCE_GROUP"
            # Compute layer (APIM AI Gateway + Key Vault) — scenarios 02 & 03.
            "APIM_GATEWAY_URL"                      = "APIM_GATEWAY_URL"
            "APIM_OPENAI_GATEWAY_URL"               = "APIM_OPENAI_GATEWAY_URL"
            "APIM_AGENTS_KEY_SECRET_NAME"           = "APIM_AGENTS_KEY_SECRET_NAME"
            "APIM_OPENAI_KEY_SECRET_NAME"           = "APIM_OPENAI_KEY_SECRET_NAME"
            "KEYVAULT_URI"                          = "KEYVAULT_URI"
        }
        foreach ($src in $map.Keys) {
            if ($azdValues.ContainsKey($src) -and -not [string]::IsNullOrWhiteSpace($azdValues[$src])) {
                Set-EnvIfEmpty -Key $map[$src] -Value $azdValues[$src] | Out-Null
            }
        }
        Set-EnvIfEmpty -Key "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED" -Value "false" | Out-Null
        Set-EnvIfEmpty -Key "AZURE_LOG_LEVEL" -Value "error" | Out-Null

        Write-Host ""
        Write-Host "  ============================================================" -ForegroundColor Cyan
        Write-Host "   .env hydrated from azd environment. You're ready to run." -ForegroundColor Cyan
        Write-Host "  ============================================================" -ForegroundColor Cyan
        Write-Host ""
        exit 0
    }
}

# ────────────────────────────────────────────────────────────
#  Step 1: Check Azure CLI login
# ────────────────────────────────────────────────────────────
Write-Host "[1/5] Checking Azure CLI authentication..." -ForegroundColor Blue

$azExists = Get-Command az -ErrorAction SilentlyContinue
if (-not $azExists) {
    Write-Host "  [X] Azure CLI (az) is not installed." -ForegroundColor Red
    Write-Host "      Install it: https://learn.microsoft.com/cli/azure/install-azure-cli"
    exit 1
}

$azAccount = $null
try {
    $azAccount = az account show 2>$null | ConvertFrom-Json
}
catch { }

if (-not $azAccount) {
    Write-Host "  [!] Not logged in to Azure CLI." -ForegroundColor Yellow
    Write-Host "      Running 'az login --use-device-code'..." -ForegroundColor Yellow
    Write-Host ""
    az login --use-device-code
    Write-Host ""
    try {
        $azAccount = az account show 2>$null | ConvertFrom-Json
    }
    catch { }
    if (-not $azAccount) {
        Write-Host "  [X] Azure login failed. Please try again." -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] Login successful!" -ForegroundColor Green
}

$AccountName = $azAccount.user.name
$SubscriptionName = $azAccount.name
Write-Host "  [OK] Logged in as: ${AccountName}" -ForegroundColor Green
Write-Host "  [OK] Subscription: ${SubscriptionName}" -ForegroundColor Green

# ────────────────────────────────────────────────────────────
#  Step 2: Create .env from .env.sample if it doesn't exist
# ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/5] Checking .env file..." -ForegroundColor Blue

if (-not (Test-Path $SampleFile)) {
    Write-Host "  [X] .env.sample not found at: ${SampleFile}" -ForegroundColor Red
    Write-Host "      Make sure you're running this script from the demo-agent-observability directory."
    exit 1
}

if (-not (Test-Path $EnvFile)) {
    Copy-Item $SampleFile $EnvFile
    Write-Host "  [OK] Created .env from .env.sample" -ForegroundColor Green
}
else {
    Write-Host "  [OK] .env already exists (will update empty values)" -ForegroundColor Green
    # Ensure any new keys from sample are present
    $sampleKeys = Get-Content $SampleFile | Where-Object { $_ -match "^[A-Z]" } | ForEach-Object { ($_ -split "=", 2)[0] }
    $envContent = Get-Content $EnvFile -Raw
    foreach ($key in $sampleKeys) {
        if ($envContent -notmatch "(?m)^${key}=") {
            Add-Content -Path $EnvFile -Value "${key}="
            Write-Host "  [+] Added new key: ${key}" -ForegroundColor Green
        }
    }
}

# ────────────────────────────────────────────────────────────
#  Step 3: Get resource group from user & subscription info
# ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[3/5] Azure resource configuration..." -ForegroundColor Blue

$SubId = $azAccount.id
Set-EnvIfEmpty -Key "AZURE_SUBSCRIPTION_ID" -Value $SubId | Out-Null

Write-Host ""
$SelectedRG = Read-Host "  Enter your Azure resource group name"

if ([string]::IsNullOrWhiteSpace($SelectedRG)) {
    Write-Host "  [X] Resource group name cannot be empty." -ForegroundColor Red
    exit 1
}

# Validate the resource group exists
$rgCheck = $null
try {
    $rgCheck = az group show --name $SelectedRG 2>$null | ConvertFrom-Json
}
catch { }

if (-not $rgCheck) {
    Write-Host "  [X] Resource group '${SelectedRG}' not found in subscription '${SubscriptionName}'." -ForegroundColor Red
    Write-Host "      Check the name and make sure you're logged in to the correct subscription." -ForegroundColor Red
    exit 1
}

Write-Host "  [OK] Using resource group: ${SelectedRG}" -ForegroundColor Green
Set-EnvIfEmpty -Key "AZURE_RESOURCE_GROUP" -Value $SelectedRG | Out-Null

# ────────────────────────────────────────────────────────────
#  Step 4: Discover resources in the resource group
# ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[4/5] Discovering resources in ${SelectedRG}..." -ForegroundColor Blue

# ── Find AI Services account ──
$AiAccountName = $null
try {
    $AiAccountName = az cognitiveservices account list `
        --resource-group $SelectedRG `
        --query "[?kind=='AIServices' || kind=='OpenAI'] | [0].name" `
        -o tsv 2>$null
}
catch { }

if ([string]::IsNullOrWhiteSpace($AiAccountName)) {
    Write-Host "  [!] No AI Services accounts found in resource group '${SelectedRG}'." -ForegroundColor Yellow
    Write-Host "      Create a Foundry project first (see setup docs)." -ForegroundColor Yellow
}
else {
    Write-Host "  [OK] AI Services account: ${AiAccountName}" -ForegroundColor Green

    # Note: this demo authenticates with Microsoft Entra ID (DefaultAzureCredential).
    # Account keys are intentionally NOT fetched or stored.

    # ── Find Foundry project endpoint ──
    $ProjectEndpoint = $null
    try {
        $ProjectEndpoints = az cognitiveservices account project list `
            --name $AiAccountName `
            --resource-group $SelectedRG `
            --query '[].properties.endpoints."AI Foundry API"' -o tsv 2>$null
    }
    catch {
        $ProjectEndpoints = $null
    }

    if (-not [string]::IsNullOrWhiteSpace($ProjectEndpoints)) {
        $endpoints = $ProjectEndpoints -split "`n" | Where-Object { $_.Trim() -ne "" }

        if ($endpoints.Count -eq 1) {
            $ProjectEndpoint = $endpoints[0].TrimEnd("/")
            Write-Host "  [OK] Foundry project endpoint: ${ProjectEndpoint}" -ForegroundColor Green
        }
        else {
            Write-Host "  Multiple projects found:" -ForegroundColor Yellow
            foreach ($ep in $endpoints) { Write-Host "     - $ep" }
            $ProjectEndpoint = (Read-Host "  Enter the full project endpoint to use").TrimEnd("/")
        }
        Set-EnvIfEmpty -Key "AZURE_AI_PROJECT_ENDPOINT" -Value $ProjectEndpoint | Out-Null
    }
    else {
        # Fallback: try ML workspace kind=Project
        $ProjectName = $null
        try {
            $ProjectName = az resource list `
                --resource-group $SelectedRG `
                --resource-type "Microsoft.MachineLearningServices/workspaces" `
                --query "[?kind=='Project'].name | [0]" `
                -o tsv 2>$null
        }
        catch { }

        if (-not [string]::IsNullOrWhiteSpace($ProjectName)) {
            Write-Host "  [OK] Foundry project: ${ProjectName}" -ForegroundColor Green
            $ProjectEndpoint = "https://${AiAccountName}.services.ai.azure.com/api/projects/${ProjectName}"
            Set-EnvIfEmpty -Key "AZURE_AI_PROJECT_ENDPOINT" -Value $ProjectEndpoint | Out-Null
        }
        else {
            Write-Host "  [!] No Foundry project found in resource group '${SelectedRG}'" -ForegroundColor Yellow
            Write-Host "      Set AZURE_AI_PROJECT_ENDPOINT manually in .env" -ForegroundColor Yellow
        }
    }

    # ── Find model deployments (prefer GPT models) ──
    $DeployName = $null
    try {
        $DeployName = az cognitiveservices account deployment list `
            --name $AiAccountName `
            --resource-group $SelectedRG `
            --query "[?contains(properties.model.name,'gpt')].name | [0]" `
            -o tsv 2>$null
    }
    catch { }

    if ([string]::IsNullOrWhiteSpace($DeployName)) {
        try {
            $DeployName = az cognitiveservices account deployment list `
                --name $AiAccountName `
                --resource-group $SelectedRG `
                --query "[0].name" `
                -o tsv 2>$null
        }
        catch { }
    }

    if (-not [string]::IsNullOrWhiteSpace($DeployName)) {
        Write-Host "  [OK] Model deployment: ${DeployName}" -ForegroundColor Green
        Set-EnvIfEmpty -Key "AZURE_AI_MODEL_DEPLOYMENT_NAME" -Value $DeployName | Out-Null
    }
    else {
        Write-Host "  [!] No model deployments found. Deploy a model (e.g., gpt-4.1-mini) in the Foundry portal." -ForegroundColor Yellow
    }

    # ── Find Application Insights ──
    $AppInsights = $null
    $AppInsightsRG = $SelectedRG

    try {
        $AppInsights = az resource list `
            --resource-group $SelectedRG `
            --resource-type "Microsoft.Insights/components" `
            --query "[0].name" `
            -o tsv 2>$null
    }
    catch { }

    # Fallback: search subscription-wide
    if ([string]::IsNullOrWhiteSpace($AppInsights)) {
        try {
            $aiResource = az resource list `
                --resource-type "Microsoft.Insights/components" `
                --query "[0].{name:name, rg:resourceGroup}" -o json 2>$null | ConvertFrom-Json
            if ($aiResource) {
                $AppInsights = $aiResource.name
                $AppInsightsRG = $aiResource.rg
            }
        }
        catch { }
    }

    if (-not [string]::IsNullOrWhiteSpace($AppInsights)) {
        # Ensure the application-insights extension is installed
        $prevPref = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        az extension add --name application-insights --yes 2>&1 | Out-Null
        $ErrorActionPreference = $prevPref

        $TelemetryConn = $null
        try {
            $TelemetryConn = az monitor app-insights component show `
                --app $AppInsights `
                --resource-group $AppInsightsRG `
                --query "connectionString" `
                -o tsv 2>$null
        }
        catch { }

        if (-not [string]::IsNullOrWhiteSpace($TelemetryConn)) {
            Write-Host "  [OK] Application Insights: ${AppInsights}" -ForegroundColor Green
            Set-EnvIfEmpty -Key "TELEMETRY_CONNECTION_STRING" -Value $TelemetryConn | Out-Null
        }
        else {
            Write-Host "  [!] Could not retrieve App Insights connection string" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "  [!] No Application Insights found in subscription" -ForegroundColor Yellow
        Write-Host "      Set TELEMETRY_CONNECTION_STRING manually if needed for tracing" -ForegroundColor Yellow
    }
}

# Set defaults for SDK configuration variables.
# Content recording sends full prompts/responses (which may include PII) to App Insights.
# Default to "false" — flip to "true" explicitly for demo or non-production use.
Set-EnvIfEmpty -Key "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED" -Value "false" | Out-Null
Set-EnvIfEmpty -Key "AZURE_LOG_LEVEL" -Value "error" | Out-Null

# ────────────────────────────────────────────────────────────
#  Step 4.5: Verify RBAC for current user + hosted agents
# ────────────────────────────────────────────────────────────
#  The portal's "Operate > Assets" page requires explicit data
#  plane roles — subscription Owner alone is not enough.
#  Hosted agent containers also need their own roles.
# ────────────────────────────────────────────────────────────
if (-not [string]::IsNullOrWhiteSpace($AiAccountName)) {
    Write-Host ""
    Write-Host "[4.5] Checking RBAC..." -ForegroundColor Blue

    $AccountScope = "/subscriptions/${SubId}/resourceGroups/${SelectedRG}/providers/Microsoft.CognitiveServices/accounts/${AiAccountName}"
    $RgScope = "/subscriptions/${SubId}/resourceGroups/${SelectedRG}"

    # --- Current user roles ---
    $CurrentUser = $AccountName
    Write-Host "  Checking roles for: ${CurrentUser}" -ForegroundColor Gray

    # Azure AI Developer on RG
    $UserAiDev = $null
    try {
        $UserAiDev = az role assignment list --assignee $CurrentUser --role "Azure AI Developer" --scope $RgScope --query "[0].id" -o tsv 2>$null
    } catch { }
    if ([string]::IsNullOrWhiteSpace($UserAiDev)) {
        Write-Host "  [!] Missing: Azure AI Developer on RG — assigning..." -ForegroundColor Yellow
        try { az role assignment create --assignee $CurrentUser --role "Azure AI Developer" --scope $RgScope -o none 2>$null; Write-Host "  [OK] Azure AI Developer assigned" -ForegroundColor Green } catch { Write-Host "  [X] Failed (need Owner on RG)" -ForegroundColor Red }
    } else {
        Write-Host "  [OK] Azure AI Developer on RG" -ForegroundColor Green
    }

    # Cognitive Services User on the account
    $UserCogUser = $null
    try {
        $UserCogUser = az role assignment list --assignee $CurrentUser --role "Cognitive Services User" --scope $AccountScope --query "[0].id" -o tsv 2>$null
    } catch { }
    if ([string]::IsNullOrWhiteSpace($UserCogUser)) {
        Write-Host "  [!] Missing: Cognitive Services User on account — assigning..." -ForegroundColor Yellow
        try { az role assignment create --assignee $CurrentUser --role "Cognitive Services User" --scope $AccountScope -o none 2>$null; Write-Host "  [OK] Cognitive Services User assigned" -ForegroundColor Green } catch { Write-Host "  [X] Failed (need Owner on account)" -ForegroundColor Red }
    } else {
        Write-Host "  [OK] Cognitive Services User on account" -ForegroundColor Green
    }

    # --- Hosted agent identity roles ---
    $AccountPrincipalId = $null
    try {
        $AccountPrincipalId = az cognitiveservices account show `
            --name $AiAccountName `
            --resource-group $SelectedRG `
            --query "identity.principalId" -o tsv 2>$null
    }
    catch { }

    if (-not [string]::IsNullOrWhiteSpace($AccountPrincipalId)) {
        Write-Host "  AI account managed identity: ${AccountPrincipalId}" -ForegroundColor Gray

        $AccountScope = "/subscriptions/${SubId}/resourceGroups/${SelectedRG}/providers/Microsoft.CognitiveServices/accounts/${AiAccountName}"
        $RgScope = "/subscriptions/${SubId}/resourceGroups/${SelectedRG}"

        # Check for Cognitive Services User on the account
        $CogUserRole = $null
        try {
            $CogUserRole = az role assignment list `
                --assignee $AccountPrincipalId `
                --role "Cognitive Services User" `
                --scope $AccountScope `
                --query "[0].id" -o tsv 2>$null
        }
        catch { }

        if ([string]::IsNullOrWhiteSpace($CogUserRole)) {
            Write-Host "  [!] Missing: Cognitive Services User on AI account" -ForegroundColor Yellow
            Write-Host "      Assigning..." -ForegroundColor Yellow
            try {
                az role assignment create `
                    --assignee-object-id $AccountPrincipalId `
                    --assignee-principal-type ServicePrincipal `
                    --role "Cognitive Services User" `
                    --scope $AccountScope -o none 2>$null
                Write-Host "  [OK] Cognitive Services User assigned" -ForegroundColor Green
            }
            catch {
                Write-Host "  [X] Failed to assign role (need Owner/User Access Admin on the account)" -ForegroundColor Red
            }
        }
        else {
            Write-Host "  [OK] Cognitive Services User already assigned" -ForegroundColor Green
        }

        # Check for Azure AI Developer on the resource group
        $AiDevRole = $null
        try {
            $AiDevRole = az role assignment list `
                --assignee $AccountPrincipalId `
                --role "Azure AI Developer" `
                --scope $RgScope `
                --query "[0].id" -o tsv 2>$null
        }
        catch { }

        if ([string]::IsNullOrWhiteSpace($AiDevRole)) {
            Write-Host "  [!] Missing: Azure AI Developer on resource group" -ForegroundColor Yellow
            Write-Host "      Assigning..." -ForegroundColor Yellow
            try {
                az role assignment create `
                    --assignee-object-id $AccountPrincipalId `
                    --assignee-principal-type ServicePrincipal `
                    --role "Azure AI Developer" `
                    --scope $RgScope -o none 2>$null
                Write-Host "  [OK] Azure AI Developer assigned" -ForegroundColor Green
            }
            catch {
                Write-Host "  [X] Failed to assign role (need Owner/User Access Admin on the RG)" -ForegroundColor Red
            }
        }
        else {
            Write-Host "  [OK] Azure AI Developer already assigned" -ForegroundColor Green
        }
    }
    else {
        Write-Host "  [!] AI account has no system-assigned identity. Hosted agents won't work." -ForegroundColor Yellow
        Write-Host "      Enable it: az cognitiveservices account identity assign --name ${AiAccountName} --resource-group ${SelectedRG}" -ForegroundColor Yellow
    }

    # --- Agent identity (platform-managed, injected into hosted containers via AZURE_CLIENT_ID) ---
    $AgentIdentityId = $null
    try {
        $AgentIdentityId = az cognitiveservices account project show `
            -n $AiAccountName --project-name (Split-Path $ProjectEndpoint -Leaf) `
            -g $SelectedRG --query "properties.agentIdentity.agentIdentityId" -o tsv 2>$null
    }
    catch { }

    if (-not [string]::IsNullOrWhiteSpace($AgentIdentityId)) {
        Write-Host "  Agent identity: ${AgentIdentityId}" -ForegroundColor Gray

        $AgentCogUser = $null
        try { $AgentCogUser = az role assignment list --assignee $AgentIdentityId --role "Cognitive Services User" --scope $AccountScope --query "[0].id" -o tsv 2>$null } catch { }
        if ([string]::IsNullOrWhiteSpace($AgentCogUser)) {
            Write-Host "  [!] Missing: Cognitive Services User for agent identity — assigning..." -ForegroundColor Yellow
            try { az role assignment create --assignee-object-id $AgentIdentityId --assignee-principal-type ServicePrincipal --role "Cognitive Services User" --scope $AccountScope -o none 2>$null; Write-Host "  [OK] Assigned" -ForegroundColor Green } catch { Write-Host "  [X] Failed" -ForegroundColor Red }
        } else { Write-Host "  [OK] Agent identity: Cognitive Services User" -ForegroundColor Green }

        $AgentAiDev = $null
        try { $AgentAiDev = az role assignment list --assignee $AgentIdentityId --role "Azure AI Developer" --scope $AccountScope --query "[0].id" -o tsv 2>$null } catch { }
        if ([string]::IsNullOrWhiteSpace($AgentAiDev)) {
            Write-Host "  [!] Missing: Azure AI Developer for agent identity — assigning..." -ForegroundColor Yellow
            try { az role assignment create --assignee-object-id $AgentIdentityId --assignee-principal-type ServicePrincipal --role "Azure AI Developer" --scope $AccountScope -o none 2>$null; Write-Host "  [OK] Assigned" -ForegroundColor Green } catch { Write-Host "  [X] Failed" -ForegroundColor Red }
        } else { Write-Host "  [OK] Agent identity: Azure AI Developer" -ForegroundColor Green }
    }
}

# ────────────────────────────────────────────────────────────
#  Step 5: Final report
# ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[5/5] Verifying .env configuration..." -ForegroundColor Blue
Write-Host ""

$Missing = 0
$OptionalVars = @(
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
    "TELEMETRY_CONNECTION_STRING",
    "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED",
    "AZURE_LOG_LEVEL",
    "ACR_NAME"
)

$envLines = Get-Content $EnvFile | Where-Object { $_ -match "^[A-Z]" }
foreach ($line in $envLines) {
    $parts = $line -split "=", 2
    $key = $parts[0]
    $value = if ($parts.Count -gt 1) { $parts[1].Trim().Trim('"') } else { "" }
    $isOptional = $OptionalVars -contains $key

    if ([string]::IsNullOrWhiteSpace($value)) {
        if ($isOptional) {
            Write-Host "  [ ] ${key} - not set (optional)" -ForegroundColor Yellow
        }
        else {
            Write-Host "  [X] ${key} - NOT SET" -ForegroundColor Red
            $Missing++
        }
    }
    else {
        $display = if ($value.Length -gt 40) { $value.Substring(0, 40) + "..." } else { $value }
        Write-Host "  [OK] ${key} = ${display}" -ForegroundColor Green
    }
}

Write-Host ""
if ($Missing -eq 0) {
    Write-Host "  ============================================================" -ForegroundColor Green
    Write-Host "   All required variables are set! You're ready to go.        " -ForegroundColor Green
    Write-Host "  ============================================================" -ForegroundColor Green
}
else {
    Write-Host "  ============================================================" -ForegroundColor Yellow
    Write-Host "   ${Missing} variable(s) need manual entry.                  " -ForegroundColor Yellow
    Write-Host "   Edit: ${EnvFile}" -ForegroundColor Yellow
    Write-Host "  ============================================================" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  .env location: ${EnvFile}" -ForegroundColor Cyan
Write-Host "  Reference:     ${SampleFile}" -ForegroundColor Cyan
Write-Host ""
