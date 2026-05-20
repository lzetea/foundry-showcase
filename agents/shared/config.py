"""
Shared configuration — loads environment variables and creates Foundry clients.

All demo scripts import from here to avoid duplicating setup logic.

Authentication: we use Microsoft Entra ID via DefaultAzureCredential. No account
keys are read or stored by this demo — the Foundry Responses / Evals / Red-Team
APIs all accept AAD tokens through the AIProjectClient.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT_DIR / "data" / "contoso-travel"

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv(ROOT_DIR / ".env", override=True)

ENDPOINT = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
MODEL_NAME = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5")


def _check_env():
    """Validate that required environment variables are set."""
    if not ENDPOINT:
        print("ERROR: AZURE_AI_PROJECT_ENDPOINT is not set.")
        print(f"Copy .env.sample to .env in {ROOT_DIR} and fill in the values.")
        sys.exit(1)


def get_clients(*, allow_preview: bool = False):
    """Return ``(project_client, openai_client)`` built from the shared env."""
    _check_env()
    credential = DefaultAzureCredential()
    kwargs = {"endpoint": ENDPOINT, "credential": credential}
    if allow_preview:
        kwargs["allow_preview"] = True
    project_client = AIProjectClient(**kwargs)
    openai_client = project_client.get_openai_client()
    return project_client, openai_client


def get_credential():
    """Return a DefaultAzureCredential instance."""
    return DefaultAzureCredential()
