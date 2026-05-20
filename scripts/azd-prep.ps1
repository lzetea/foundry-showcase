# ============================================================
#  Foundry Control Plane — Agent Observability Demo
#  azd Pre-Deploy Preparation Script (PowerShell)
# ============================================================
#  Populates the minimum required azd environment variables so
#  that `azd up` can deploy the Bicep in infra/ without any
#  manual value entry.
#
#  What it does:
#    1. Verifies Azure CLI + azd are installed and logged in
#    2. Initialises the azd environment (if none exists)
#    3. Sets AZURE_LOCATION, AZURE_PRINCIPAL_ID, AZURE_PRINCIPAL_TYPE
#    4. Leaves optional knobs (ENABLE_COMPUTE_LAYER, existing-*
#       resource IDs, etc.) alone so greenfield is the default
#
#  Usage:
#    .\scripts\azd-prep.ps1 [-EnvName <name>] [-Location <region>] [-DisableComputeLayer]
#
#  After running, just execute:   azd up
# ============================================================

[CmdletBinding()]
param(
    [string]$EnvName,
    [string]$Location,
    [switch]$DisableComputeLayer
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
Push-Location $RepoRoot
try {

    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "   Foundry Agent Observability - azd Pre-Deploy Prep" -ForegroundColor Cyan
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""

    # --- Check prerequisites ---
    foreach ($cmd in @('az', 'azd')) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
            Write-Host "  [X] '$cmd' is not installed or not on PATH." -ForegroundColor Red
            Write-Host "      az:  https://learn.microsoft.com/cli/azure/install-azure-cli"
            Write-Host "      azd: https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd"
            exit 1
        }
    }

    # --- Azure CLI login ---
    Write-Host "[1/4] Verifying Azure CLI login..." -ForegroundColor Blue
    $azAccount = $null
    try { $azAccount = az account show 2>$null | ConvertFrom-Json } catch { }
    if (-not $azAccount) {
        Write-Host "  [!] Not logged in. Running 'az login --use-device-code'..." -ForegroundColor Yellow
        az login --use-device-code | Out-Null
        $azAccount = az account show 2>$null | ConvertFrom-Json
        if (-not $azAccount) { Write-Host "  [X] Login failed." -ForegroundColor Red; exit 1 }
    }
    Write-Host "  [OK] $($azAccount.user.name) - $($azAccount.name)" -ForegroundColor Green

    # --- azd login (shares token cache with az on most setups, but check explicitly) ---
    Write-Host ""
    Write-Host "[2/4] Verifying azd login..." -ForegroundColor Blue
    $azdStatus = azd auth login --check-status 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [!] azd not logged in. Running 'azd auth login'..." -ForegroundColor Yellow
        azd auth login
        if ($LASTEXITCODE -ne 0) { Write-Host "  [X] azd login failed." -ForegroundColor Red; exit 1 }
    }
    Write-Host "  [OK] azd authenticated" -ForegroundColor Green

    # --- Select or create azd environment ---
    Write-Host ""
    Write-Host "[3/4] Selecting azd environment..." -ForegroundColor Blue

    $currentEnv = $null
    try { $currentEnv = (azd env get-value AZURE_ENV_NAME 2>$null) } catch { }

    if ($EnvName) {
        # Create if missing, then select
        $existing = (azd env list --output json 2>$null | ConvertFrom-Json) | Where-Object { $_.Name -eq $EnvName }
        if (-not $existing) {
            azd env new $EnvName --no-prompt | Out-Null
            Write-Host "  [OK] Created azd environment '$EnvName'" -ForegroundColor Green
        } else {
            azd env select $EnvName | Out-Null
            Write-Host "  [OK] Selected existing azd environment '$EnvName'" -ForegroundColor Green
        }
    }
    elseif (-not $currentEnv) {
        $inputName = Read-Host "  Enter a name for the azd environment (e.g. 'foundry-obs-dev')"
        if ([string]::IsNullOrWhiteSpace($inputName)) {
            Write-Host "  [X] Environment name is required." -ForegroundColor Red; exit 1
        }
        azd env new $inputName --no-prompt | Out-Null
        Write-Host "  [OK] Created azd environment '$inputName'" -ForegroundColor Green
    }
    else {
        Write-Host "  [OK] Using existing azd environment '$currentEnv'" -ForegroundColor Green
    }

    # --- Populate required parameters ---
    Write-Host ""
    Write-Host "[4/4] Populating azd environment variables..." -ForegroundColor Blue

    # Subscription (azd picks this up automatically, but set it explicitly for clarity)
    azd env set AZURE_SUBSCRIPTION_ID $azAccount.id | Out-Null
    Write-Host "  [OK] AZURE_SUBSCRIPTION_ID = $($azAccount.id)" -ForegroundColor Green

    # Location
    if (-not $Location) {
        $existingLoc = (azd env get-value AZURE_LOCATION 2>$null)
        if ([string]::IsNullOrWhiteSpace($existingLoc)) {
            $Location = Read-Host "  Azure region (default: eastus2)"
            if ([string]::IsNullOrWhiteSpace($Location)) { $Location = "eastus2" }
        } else {
            $Location = $existingLoc
        }
    }
    azd env set AZURE_LOCATION $Location | Out-Null
    Write-Host "  [OK] AZURE_LOCATION = $Location" -ForegroundColor Green

    # Principal (signed-in user) — needed for Bicep role assignments
    $principalId = az ad signed-in-user show --query id -o tsv 2>$null
    if ([string]::IsNullOrWhiteSpace($principalId)) {
        Write-Host "  [X] Could not resolve signed-in user objectId via 'az ad signed-in-user show'." -ForegroundColor Red
        Write-Host "      If you are signed in as a service principal, set AZURE_PRINCIPAL_ID manually." -ForegroundColor Yellow
        exit 1
    }
    azd env set AZURE_PRINCIPAL_ID $principalId | Out-Null
    azd env set AZURE_PRINCIPAL_TYPE "User" | Out-Null
    Write-Host "  [OK] AZURE_PRINCIPAL_ID = $principalId (User)" -ForegroundColor Green

    # Compute layer (ACA + Cosmos + KV + APIM) — enabled by default for a complete PoC.
    if ($DisableComputeLayer) {
        azd env set ENABLE_COMPUTE_LAYER "false" | Out-Null
        Write-Host "  [OK] ENABLE_COMPUTE_LAYER = false (Foundry-only deployment)" -ForegroundColor Green
    } else {
        azd env set ENABLE_COMPUTE_LAYER "true" | Out-Null
        Write-Host "  [OK] ENABLE_COMPUTE_LAYER = true (ACA + Cosmos + KV + APIM will be deployed)" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host "   Ready. Next step:   azd up" -ForegroundColor Cyan
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  After deployment, run 'setup-env.ps1' to hydrate the local .env" -ForegroundColor Gray
    Write-Host "  file from azd outputs so the Python agents can run locally." -ForegroundColor Gray
    Write-Host ""
}
finally {
    Pop-Location
}
