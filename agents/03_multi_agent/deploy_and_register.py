"""
Scenario 03 — Build, deploy, and register the multi-agent MAF workflow on ACA.

Phases:
  1. ACR cloud build (Linux/amd64 image).
  2. ``az containerapp update`` — roll a new revision of the ACA app provisioned
     by Bicep (``ca-maf-agent``). Sets ``AZURE_OPENAI_ENDPOINT`` and
     ``AZURE_OPENAI_API_KEY`` so model calls route through the APIM AI Gateway.
  3. Register the APIM-fronted multi-agent endpoint as a **Foundry project
     connection** (CustomKeys, storing the APIM subscription key). The
     connection surfaces the agent as an asset in the Foundry Control Plane.
  4. Smoke-test the workflow through its APIM-fronted Responses API.

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

AGENT_NAME = "contoso-travel-multiagent"
CONNECTION_NAME = "contoso-travel-multiagent-endpoint"
CONTAINER_APP_NAME = "ca-maf-agent"
IMAGE_REPO = "contoso-travel-multiagent"
APIM_SUBROUTE = "maf"

SRC_DIR = Path(__file__).resolve().parent / "src"

SMOKE_TEST_QUERY = (
    "I need to book a 3-night trip from San Francisco to Tokyo next month. "
    "Business class flights and a 4+ star hotel with a gym. Budget is $4,000."
)


def main():
    print("=" * 70)
    print("Scenario 03 — Multi-agent (MAF HandoffBuilder) on ACA via APIM")
    print("=" * 70)

    # Steps 1-4 (ACR build, ACA roll, Foundry connection, smoke test) are shared
    # with scenario 02 and live in agents/shared/aca_connection.py. Scenario 03
    # also injects AZURE_AI_PROJECT_ENDPOINT so the MAF FoundryChatClient fallback
    # works if the APIM gateway is ever bypassed.
    image_ref = aca_connection.acr_build(IMAGE_REPO, SRC_DIR)
    project_endpoint = aca_connection.require_env("AZURE_AI_PROJECT_ENDPOINT")
    aca_connection.update_container_app(
        CONTAINER_APP_NAME,
        image_ref,
        extra_env={"AZURE_AI_PROJECT_ENDPOINT": project_endpoint},
    )

    project_client, _ = get_clients()
    aca_connection.ensure_foundry_connection(
        project_client,
        CONNECTION_NAME,
        APIM_SUBROUTE,
        metadata={
            "scenario": "03_multi_agent",
            "backend": "azure-container-apps",
            "gateway": "apim",
            "topology": "handoff",
        },
    )
    aca_connection.smoke_test(APIM_SUBROUTE, SMOKE_TEST_QUERY, MODEL_NAME)

    print("\n" + "=" * 70)
    print(f"Deployed image: {image_ref}")
    print(f"Connection:     {CONNECTION_NAME}")
    print("Use: python -m agents.shared.trace    --scenario 03_multi_agent")
    print("     python -m agents.shared.evaluate --scenario 03_multi_agent")
    print("     python -m agents.shared.redteam  --scenario 03_multi_agent")
    print("=" * 70)


if __name__ == "__main__":
    main()
