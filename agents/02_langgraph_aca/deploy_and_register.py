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

from pathlib import Path

from agents.shared import aca_connection
from agents.shared.config import MODEL_NAME, get_clients

AGENT_NAME = "contoso-travel-langgraph-aca"
CONNECTION_NAME = "contoso-travel-langgraph-aca-endpoint"
CONTAINER_APP_NAME = "ca-langgraph-agent"
IMAGE_REPO = "contoso-travel-langgraph-aca"
APIM_SUBROUTE = "langgraph"

SRC_DIR = Path(__file__).resolve().parent / "src"

SMOKE_TEST_QUERY = "What flights are available from San Francisco to Tokyo?"


def main():
    print("=" * 70)
    print("Scenario 02 — LangGraph on ACA via APIM AI Gateway")
    print("=" * 70)

    # Steps 1-4 (ACR build, ACA roll, Foundry connection, smoke test) are shared
    # with scenario 03 and live in agents/shared/aca_connection.py.
    image_ref = aca_connection.acr_build(IMAGE_REPO, SRC_DIR)
    aca_connection.update_container_app(CONTAINER_APP_NAME, image_ref)

    project_client, _ = get_clients()
    aca_connection.ensure_foundry_connection(
        project_client,
        CONNECTION_NAME,
        APIM_SUBROUTE,
        metadata={
            "scenario": "02_langgraph_aca",
            "backend": "azure-container-apps",
            "gateway": "apim",
        },
    )
    aca_connection.smoke_test(APIM_SUBROUTE, SMOKE_TEST_QUERY, MODEL_NAME)

    print("\n" + "=" * 70)
    print(f"Deployed image: {image_ref}")
    print(f"Connection:     {CONNECTION_NAME}")
    print("Use: python -m agents.shared.trace    --scenario 02_langgraph_aca")
    print("     python -m agents.shared.evaluate --scenario 02_langgraph_aca")
    print("     python -m agents.shared.redteam  --scenario 02_langgraph_aca")
    print("=" * 70)


if __name__ == "__main__":
    main()
