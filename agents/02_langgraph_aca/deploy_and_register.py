"""
Scenario 02 — Build, deploy, and register the LangGraph agent on ACA.

Phases:
  1. ACR cloud build (Linux/amd64 image, no local Docker needed).
  2. ``az containerapp update`` — roll a new revision of the ACA app provisioned
     by Bicep (``ca-langgraph-agent``). Sets ``AZURE_OPENAI_ENDPOINT`` and
     ``AZURE_OPENAI_API_KEY`` so model calls route through the APIM AI Gateway.
  3. Register the APIM-fronted agent endpoint as a **Foundry project connection**
     (CustomKeys connection storing the APIM subscription key). This makes the
     endpoint discoverable as an asset in the Foundry Control Plane.
  4. Smoke-test the agent through its APIM-fronted Responses API.

Note on the Foundry "agent asset" representation:
  ``azure-ai-projects 2.0.0`` does not yet ship a ``ConnectedAgentTool`` type
  that wraps an external Responses-API endpoint as a Foundry PromptAgent.
  Until that surface lands, the **project connection itself** is the asset:
  it's visible in the portal, RBAC applies, and the shared
  ``trace``/``evaluate``/``redteam`` scripts target it via the scenario
  adapter which calls APIM directly.

Prerequisites (from ``azd up`` and ``scripts/setup-env.ps1``):
  - ``AZURE_AI_PROJECT_ENDPOINT``
  - ``ACR_NAME``, ``AZURE_RESOURCE_GROUP``
  - ``APIM_GATEWAY_URL``, ``APIM_OPENAI_GATEWAY_URL``
  - ``APIM_AGENTS_KEY_SECRET_NAME``, ``APIM_OPENAI_KEY_SECRET_NAME`` (Key Vault)
  - ``KEYVAULT_URI``
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from azure.identity import DefaultAzureCredential

from agents.shared.config import ENDPOINT, MODEL_NAME, get_clients

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AZ = shutil.which("az") or r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"

AGENT_NAME = "contoso-travel-langgraph-aca"
CONNECTION_NAME = "contoso-travel-langgraph-aca-endpoint"
CONTAINER_APP_NAME = "ca-langgraph-agent"
IMAGE_REPO = "contoso-travel-langgraph-aca"

SRC_DIR = Path(__file__).resolve().parent / "src"
_TS = time.strftime("%Y%m%d%H%M")


def _env(name: str, *, required: bool = True, default: str = "") -> str:
    value = os.environ.get(name, default).strip()
    if required and not value:
        print(f"ERROR: {name} is not set. Run scripts/setup-env.ps1 after azd up.", file=sys.stderr)
        sys.exit(1)
    return value


# =========================================================================
# Step 1 — ACR cloud build
# =========================================================================
def build_and_push() -> str:
    """Run ``az acr build`` and return the full image reference."""
    acr = _env("ACR_NAME")
    print("\n--- Step 1: ACR cloud build ---")

    # Stage the shared CSV data inside the build context.
    data_src = Path(__file__).resolve().parent.parent.parent / "data" / "contoso-travel"
    data_dst = SRC_DIR / "data"
    data_dst.mkdir(exist_ok=True)
    for f in ("flights.csv", "hotels.csv", "car_rentals.csv"):
        shutil.copy2(data_src / f, data_dst / f)

    image_name = f"{IMAGE_REPO}:{_TS}"
    full_ref = f"{acr}.azurecr.io/{image_name}"
    cmd = [
        AZ, "acr", "build",
        "--registry", acr,
        "--image", image_name,
        "--platform", "linux/amd64",
        "--file", str(SRC_DIR / "Dockerfile"),
        str(SRC_DIR),
    ]
    print(f"  az acr build --registry {acr} --image {image_name}")
    result = subprocess.run(cmd, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(f"  ERROR: ACR build failed (exit {result.returncode}).", file=sys.stderr)
        sys.exit(1)
    print(f"  Built and pushed: {full_ref}")
    return full_ref


# =========================================================================
# Step 2 — Roll a new ACA revision through the APIM OpenAI gateway
# =========================================================================
def update_container_app(image_ref: str) -> str:
    """Update the ACA revision with the new image + APIM env wiring.

    Returns the container app's ingress FQDN.
    """
    rg = _env("AZURE_RESOURCE_GROUP")
    apim_openai_url = _env("APIM_OPENAI_GATEWAY_URL")
    openai_secret_name = _env("APIM_OPENAI_KEY_SECRET_NAME")
    kv_uri = _env("KEYVAULT_URI")

    print("\n--- Step 2: Update ACA revision ---")
    # Pull the APIM OpenAI subscription key from Key Vault and plumb it into the app.
    from azure.keyvault.secrets import SecretClient
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=kv_uri, credential=credential)
    openai_key = kv_client.get_secret(openai_secret_name).value

    # Store the key as an ACA secret and reference it in an env var so it
    # doesn't leak into template metadata.
    subprocess.run(
        [AZ, "containerapp", "secret", "set",
         "--name", CONTAINER_APP_NAME,
         "--resource-group", rg,
         "--secrets", f"apim-openai-key={openai_key}"],
        check=True, encoding="utf-8", errors="replace",
    )

    cmd = [
        AZ, "containerapp", "update",
        "--name", CONTAINER_APP_NAME,
        "--resource-group", rg,
        "--image", image_ref,
        "--set-env-vars",
        f"AZURE_OPENAI_ENDPOINT={apim_openai_url}",
        "AZURE_OPENAI_API_KEY=secretref:apim-openai-key",
        f"AZURE_OPENAI_API_VERSION={os.environ.get('APIM_OPENAI_API_VERSION', '2024-10-21')}",
    ]
    print(f"  az containerapp update --name {CONTAINER_APP_NAME} --image {image_ref}")
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print((result.stderr or result.stdout or "").strip(), file=sys.stderr)
        sys.exit(1)

    # Fetch the ingress FQDN.
    fqdn = subprocess.run(
        [AZ, "containerapp", "show",
         "--name", CONTAINER_APP_NAME,
         "--resource-group", rg,
         "--query", "properties.configuration.ingress.fqdn",
         "-o", "tsv"],
        check=True, capture_output=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    print(f"  Ingress: https://{fqdn}")
    return fqdn


# =========================================================================
# Step 3 — Register the APIM endpoint as a Foundry project connection
# =========================================================================
def ensure_foundry_connection(project_client) -> str:
    """Create or update a CustomKeys connection pointing at the APIM /agents/langgraph surface."""
    apim_gw = _env("APIM_GATEWAY_URL")
    agents_secret_name = _env("APIM_AGENTS_KEY_SECRET_NAME")
    kv_uri = _env("KEYVAULT_URI")

    print("\n--- Step 3: Foundry project connection ---")
    endpoint_url = f"{apim_gw.rstrip('/')}/agents/langgraph"

    from azure.keyvault.secrets import SecretClient
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=kv_uri, credential=credential)
    agents_key = kv_client.get_secret(agents_secret_name).value

    # Project connection body. The SDK's connection-create surface is a thin
    # wrapper over the REST contract; use a plain dict so we don't depend on
    # optional typed models.
    body = {
        "name": CONNECTION_NAME,
        "properties": {
            "category": "CustomKeys",
            "target": endpoint_url,
            "authType": "CustomKeys",
            "credentials": {
                "keys": {
                    "Ocp-Apim-Subscription-Key": agents_key,
                },
            },
            "metadata": {
                "scenario": "02_langgraph_aca",
                "backend": "azure-container-apps",
                "gateway": "apim",
            },
        },
    }
    try:
        project_client.connections.create_or_update(
            connection_name=CONNECTION_NAME, body=body,
        )
    except AttributeError:
        # Older SDK surface.
        project_client.connections.create(connection_name=CONNECTION_NAME, body=body)
    print(f"  Connection {CONNECTION_NAME!r} -> {endpoint_url}")
    return endpoint_url


# =========================================================================
# Step 4 — Smoke test
# =========================================================================
def smoke_test(fqdn: str) -> None:
    from openai import OpenAI

    print("\n--- Step 4: Smoke test ---")
    apim_gw = _env("APIM_GATEWAY_URL")
    agents_secret_name = _env("APIM_AGENTS_KEY_SECRET_NAME")
    kv_uri = _env("KEYVAULT_URI")

    from azure.keyvault.secrets import SecretClient
    credential = DefaultAzureCredential()
    kv_client = SecretClient(vault_url=kv_uri, credential=credential)
    agents_key = kv_client.get_secret(agents_secret_name).value

    base_url = f"{apim_gw.rstrip('/')}/agents/langgraph"
    client = OpenAI(
        base_url=base_url,
        api_key=agents_key,
        default_headers={"Ocp-Apim-Subscription-Key": agents_key},
    )
    print(f"  Container:   https://{fqdn}")
    print(f"  APIM route:  {base_url}\n")

    query = "What flights are available from San Francisco to Tokyo?"
    print(f"User: {query}")

    for attempt in range(24):  # up to ~2 minutes cold start
        try:
            response = client.responses.create(input=query, model="gpt-5")
            print(f"Assistant: {response.output_text}")
            return
        except Exception as e:
            msg = str(e)
            transient = "503" in msg or "504" in msg or "timeout" in msg.lower() or "starting" in msg.lower()
            if transient and attempt < 23:
                print(".", end="", flush=True)
                time.sleep(5)
                continue
            raise


# =========================================================================
# Main
# =========================================================================
def main():
    print("=" * 70)
    print("Scenario 02 — LangGraph on ACA via APIM AI Gateway")
    print("=" * 70)

    image_ref = build_and_push()
    fqdn = update_container_app(image_ref)
    project_client, _ = get_clients()
    ensure_foundry_connection(project_client)
    smoke_test(fqdn)

    print("\n" + "=" * 70)
    print(f"Deployed image: {image_ref}")
    print(f"Connection:     {CONNECTION_NAME}")
    print("Use: python -m agents.shared.trace    --scenario 02_langgraph_aca")
    print("     python -m agents.shared.evaluate --scenario 02_langgraph_aca")
    print("     python -m agents.shared.redteam  --scenario 02_langgraph_aca")
    print("=" * 70)


if __name__ == "__main__":
    main()
