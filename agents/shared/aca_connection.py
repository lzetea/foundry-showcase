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
import sys
import time
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Deploy/register helpers shared by scenarios 02 and 03
# ---------------------------------------------------------------------------
# Repo-root sample data staged into each scenario's Docker build context.
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "contoso-travel"


def require_env(name: str) -> str:
    """Return a required env var, or exit with a clear setup hint."""
    value = os.environ.get(name, "").strip()
    if not value:
        print(
            f"ERROR: {name} is not set. Run scripts/setup-env.ps1 after azd up.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def _kv_secret(secret_name: str) -> str:
    """Fetch a Key Vault secret value via AAD (vault from ``KEYVAULT_URI``)."""
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    kv_uri = require_env("KEYVAULT_URI")
    kv = SecretClient(vault_url=kv_uri, credential=DefaultAzureCredential())
    return kv.get_secret(secret_name).value


def acr_build(image_repo: str, src_dir: Path | str, *, stage_data: bool = True) -> str:
    """``az acr build`` the scenario image; return the full image reference.

    The only per-scenario differences are the image repo and the build context,
    so scenarios 02 / 03 share this. When ``stage_data`` is set, the shared
    Contoso CSVs are copied into ``<src_dir>/data`` so they land in the context.
    """
    src_dir = Path(src_dir)
    acr = require_env("ACR_NAME")
    print("\n--- Step 1: ACR cloud build ---")

    if stage_data:
        data_dst = src_dir / "data"
        data_dst.mkdir(exist_ok=True)
        for f in ("flights.csv", "hotels.csv", "car_rentals.csv"):
            shutil.copy2(_DATA_DIR / f, data_dst / f)

    image_name = f"{image_repo}:{time.strftime('%Y%m%d%H%M')}"
    full_ref = f"{acr}.azurecr.io/{image_name}"
    cmd = [
        AZ, "acr", "build",
        "--registry", acr,
        "--image", image_name,
        "--platform", "linux/amd64",
        "--file", str(src_dir / "Dockerfile"),
        str(src_dir),
    ]
    print(f"  az acr build --registry {acr} --image {image_name}")
    result = subprocess.run(cmd, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(f"  ERROR: ACR build failed (exit {result.returncode}).", file=sys.stderr)
        sys.exit(1)
    print(f"  Built and pushed: {full_ref}")
    return full_ref


def update_container_app(
    container_app_name: str,
    image_ref: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> str:
    """Roll a new ACA revision with the image + APIM OpenAI-gateway wiring.

    Pulls the APIM ``openai`` subscription key from Key Vault, stages it as an
    ACA secret, and routes the container's model calls through the gateway.
    Returns the ingress FQDN. ``extra_env`` carries per-scenario extras (e.g.
    scenario 03 also sets ``AZURE_AI_PROJECT_ENDPOINT``).
    """
    rg = require_env("AZURE_RESOURCE_GROUP")
    apim_openai_url = require_env("APIM_OPENAI_GATEWAY_URL")
    openai_secret_name = require_env("APIM_OPENAI_KEY_SECRET_NAME")
    api_version = os.environ.get("APIM_OPENAI_API_VERSION", "2024-10-21")

    print("\n--- Step 2: Update ACA revision ---")
    openai_key = _kv_secret(openai_secret_name)

    # Store the key as an ACA secret and reference it from an env var so it
    # never lands in template metadata.
    subprocess.run(
        [AZ, "containerapp", "secret", "set",
         "--name", container_app_name,
         "--resource-group", rg,
         "--secrets", f"apim-openai-key={openai_key}"],
        check=True, encoding="utf-8", errors="replace",
    )

    env_args = [
        f"AZURE_OPENAI_ENDPOINT={apim_openai_url}",
        "AZURE_OPENAI_API_KEY=secretref:apim-openai-key",
        f"AZURE_OPENAI_API_VERSION={api_version}",
    ]
    for key, value in (extra_env or {}).items():
        env_args.append(f"{key}={value}")

    cmd = [
        AZ, "containerapp", "update",
        "--name", container_app_name,
        "--resource-group", rg,
        "--image", image_ref,
        "--set-env-vars", *env_args,
    ]
    print(f"  az containerapp update --name {container_app_name} --image {image_ref}")
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print((result.stderr or result.stdout or "").strip(), file=sys.stderr)
        sys.exit(1)

    fqdn = subprocess.run(
        [AZ, "containerapp", "show",
         "--name", container_app_name,
         "--resource-group", rg,
         "--query", "properties.configuration.ingress.fqdn",
         "-o", "tsv"],
        check=True, capture_output=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    print(f"  Ingress: https://{fqdn}")
    return fqdn


def ensure_foundry_connection(
    project_client,
    connection_name: str,
    subroute: str,
    metadata: dict | None = None,
) -> str:
    """Create/update a CustomKeys Foundry project connection for an APIM agent route.

    Returns the connection target URL. Shared by scenarios 02 / 03.
    """
    apim_gw = require_env("APIM_GATEWAY_URL")
    agents_secret_name = require_env("APIM_AGENTS_KEY_SECRET_NAME")

    print("\n--- Step 3: Foundry project connection ---")
    endpoint_url = f"{apim_gw.rstrip('/')}/agents/{subroute.strip('/')}"
    agents_key = _kv_secret(agents_secret_name)

    body = {
        "name": connection_name,
        "properties": {
            "category": "CustomKeys",
            "target": endpoint_url,
            "authType": "CustomKeys",
            "credentials": {
                "keys": {
                    "Ocp-Apim-Subscription-Key": agents_key,
                },
            },
            "metadata": metadata or {},
        },
    }
    try:
        project_client.connections.create_or_update(
            connection_name=connection_name, body=body,
        )
    except AttributeError:
        # Older SDK surface.
        project_client.connections.create(connection_name=connection_name, body=body)
    print(f"  Connection {connection_name!r} -> {endpoint_url}")
    return endpoint_url


def smoke_test(subroute: str, query: str, model: str, *, max_attempts: int = 24) -> None:
    """Invoke the APIM-fronted agent Responses API, tolerating ACA cold start.

    Shared by scenarios 02 / 03.
    """
    print("\n--- Step 4: Smoke test ---")
    client = apim_agents_client(subroute)
    print(f"  APIM route:  {client.base_url}\n")
    print(f"User: {query}")

    for attempt in range(max_attempts):
        try:
            response = client.responses.create(input=query, model=model)
            print(f"\nAssistant: {response.output_text}")
            return
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            transient = (
                "503" in msg or "504" in msg
                or "timeout" in msg.lower() or "starting" in msg.lower()
            )
            if transient and attempt < max_attempts - 1:
                print(".", end="", flush=True)
                time.sleep(5)
                continue
            raise
