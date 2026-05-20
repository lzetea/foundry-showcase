"""Shared helpers for scenarios 02 and 03 (ACA + Foundry connection + APIM).

These scenarios both:

* Roll a new revision on an ACA app provisioned by Bicep.
* Register the APIM-fronted endpoint as a Foundry project connection.
* Invoke the APIM surface with the agents subscription key pulled from KV.

The helpers below are the small, shared subset of that lifecycle so
``deploy_and_register.py`` / ``scenario.py`` / ``cleanup.py`` in each
scenario stay focused on the per-scenario differences (image repo,
container app name, APIM subroute, connection name).
"""

from __future__ import annotations

import os
import shutil
import subprocess

from openai import OpenAI

# Public placeholder image baked into the Bicep: this is what the ACA app
# serves before ``deploy_and_register.py`` rolls the scenario image, and what
# ``cleanup.py`` rolls back to.
PLACEHOLDER_IMAGE = "mcr.microsoft.com/k8se/quickstart:latest"

AZ = shutil.which("az") or r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"


def current_revision(container_app_name: str) -> str:
    """Return the active ACA revision name for version tagging, or ``"unknown"``."""
    rg = os.environ.get("AZURE_RESOURCE_GROUP", "").strip()
    if not rg:
        return "unknown"
    try:
        result = subprocess.run(
            [AZ, "containerapp", "revision", "list",
             "--name", container_app_name,
             "--resource-group", rg,
             "--query", "[?properties.active].name | [0]",
             "-o", "tsv"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15,
        )
        return (result.stdout or "unknown").strip() or "unknown"
    except Exception:
        return "unknown"


def apim_agents_client(subroute: str) -> OpenAI:
    """Build an ``OpenAI`` client against ``APIM_GATEWAY_URL/agents/<subroute>``.

    The APIM agents subscription key is pulled from Key Vault on demand.
    """
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    gw = os.environ["APIM_GATEWAY_URL"].rstrip("/")
    kv_uri = os.environ["KEYVAULT_URI"]
    secret_name = os.environ["APIM_AGENTS_KEY_SECRET_NAME"]

    kv = SecretClient(vault_url=kv_uri, credential=DefaultAzureCredential())
    key = kv.get_secret(secret_name).value

    return OpenAI(
        base_url=f"{gw}/agents/{subroute.strip('/')}",
        api_key=key,
        default_headers={"Ocp-Apim-Subscription-Key": key},
    )


def rollback_container_app(container_app_name: str) -> None:
    """Roll the ACA app back to the placeholder image and drop the APIM env vars.

    Idempotent and tolerant of missing resources: used by scenario 02 / 03
    ``cleanup.py`` to undo what ``deploy_and_register.py`` did.
    """
    rg = os.environ.get("AZURE_RESOURCE_GROUP", "").strip()
    if not rg:
        print("  [skip] AZURE_RESOURCE_GROUP not set; ACA rollback skipped.")
        return

    print(f"  [aca] rolling {container_app_name} back to placeholder image")
    res = subprocess.run(
        [AZ, "containerapp", "update",
         "--name", container_app_name,
         "--resource-group", rg,
         "--image", PLACEHOLDER_IMAGE,
         "--remove-env-vars",
         "AZURE_OPENAI_ENDPOINT",
         "AZURE_OPENAI_API_KEY",
         "AZURE_OPENAI_API_VERSION",
         "AZURE_AI_PROJECT_ENDPOINT"],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip()
        if "was not found" in err.lower() or "could not be found" in err.lower():
            print(f"  [skip] container app {container_app_name} not found")
        else:
            print(f"  [warn] ACA rollback returned {res.returncode}: {err}")
        return

    # Best-effort: drop the secret we staged (ignores "not found").
    subprocess.run(
        [AZ, "containerapp", "secret", "remove",
         "--name", container_app_name,
         "--resource-group", rg,
         "--secret-names", "apim-openai-key"],
        capture_output=True, encoding="utf-8", errors="replace",
    )


def delete_foundry_connection(project_client, connection_name: str) -> None:
    """Best-effort deletion of a Foundry project connection."""
    try:
        project_client.connections.delete(connection_name=connection_name)
        print(f"  [deleted] connection {connection_name}")
    except Exception as exc:
        msg = str(exc).lower()
        if "not found" in msg or "404" in msg:
            print(f"  [skip] connection {connection_name} not found")
        else:
            print(f"  [warn] connection {connection_name} could not be deleted: {exc}")
