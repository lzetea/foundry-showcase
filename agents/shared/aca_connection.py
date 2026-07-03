"""Shared helpers for scenarios 02 and 03 (ACA + Foundry connection + APIM).

These scenarios both:

* Roll a new revision on an ACA app provisioned by Bicep.
* Register the APIM-fronted endpoint as a Foundry project connection.
* Invoke the APIM surface with the agents subscription key read from the ARM
  control plane (so it works even when Key Vault blocks public network access).

The helpers below are the small, shared subset of that lifecycle so
``deploy_and_register.py`` / ``scenario.py`` / ``cleanup.py`` in each
scenario stay focused on the per-scenario differences (image repo,
container app name, APIM subroute, connection name).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

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

    The APIM agents subscription key is read from the ARM control plane (not
    Key Vault) so it works even when the vault blocks public network access.
    """
    gw = require_env("APIM_GATEWAY_URL").rstrip("/")
    key = _apim_subscription_key(require_env("APIM_AGENTS_SUBSCRIPTION_RESOURCE_ID"))

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
    """Best-effort deletion of a Foundry project connection via ARM.

    ``connections.delete`` isn't on the azure-ai-projects 2.1.0 data-plane
    client, so we issue an ARM DELETE (idempotent: a 404 counts as success).
    """
    project_endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    sub = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    rg = os.environ.get("AZURE_RESOURCE_GROUP", "").strip()
    if not (project_endpoint and sub and rg):
        print("  [skip] AZURE_AI_PROJECT_ENDPOINT/SUBSCRIPTION/RESOURCE_GROUP not set")
        return
    parsed = urlparse(project_endpoint)
    account = (parsed.hostname or "").split(".")[0]
    project = parsed.path.rstrip("/").split("/")[-1]
    conn_id = (
        f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices"
        f"/accounts/{account}/projects/{project}/connections/{connection_name}"
    )
    uri = f"https://management.azure.com{conn_id}?api-version=2025-04-01-preview"
    result = subprocess.run(
        [AZ, "rest", "--method", "delete", "--uri", uri],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    err = (result.stderr or result.stdout or "").strip()
    if result.returncode == 0 or "not found" in err.lower() or "404" in err:
        print(f"  [deleted] connection {connection_name}")
    else:
        print(f"  [warn] connection {connection_name} could not be deleted: {err[:200]}")


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


def _apim_subscription_key(subscription_resource_id: str) -> str:
    """Return an APIM subscription primary key via the ARM control plane.

    Used instead of Key Vault so the flow works when the vault has public
    network access disabled - the ARM management plane stays reachable. The
    subscription resource ids come from the azd outputs
    ``APIM_OPENAI_SUBSCRIPTION_RESOURCE_ID`` / ``APIM_AGENTS_SUBSCRIPTION_RESOURCE_ID``.
    """
    uri = (
        f"https://management.azure.com{subscription_resource_id}"
        "/listSecrets?api-version=2022-08-01"
    )
    result = subprocess.run(
        [AZ, "rest", "--method", "post", "--uri", uri,
         "--query", "primaryKey", "-o", "tsv"],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    key = (result.stdout or "").strip()
    if result.returncode != 0 or not key:
        print((result.stderr or result.stdout or "").strip(), file=sys.stderr)
        print(
            "ERROR: could not read the APIM subscription key via the ARM control plane.",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


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

    Reads the APIM ``openai`` subscription key from the ARM control plane,
    stages it as an ACA secret, and routes the container's model calls through
    the gateway. Returns the ingress FQDN. ``extra_env`` carries per-scenario
    extras (e.g. scenario 03 also sets ``AZURE_AI_PROJECT_ENDPOINT``).
    """
    rg = require_env("AZURE_RESOURCE_GROUP")
    # The Azure OpenAI SDK appends ``/openai/deployments/...`` itself, so the
    # container endpoint must be the APIM base WITHOUT the ``/openai`` suffix
    # (otherwise calls hit ``/openai/openai/...`` -> 404 Resource not found).
    apim_openai_url = require_env("APIM_OPENAI_GATEWAY_URL").rstrip("/")
    if apim_openai_url.endswith("/openai"):
        apim_openai_url = apim_openai_url[: -len("/openai")]
    api_version = os.environ.get("APIM_OPENAI_API_VERSION", "2024-10-21")
    model_deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip()

    print("\n--- Step 2: Update ACA revision ---")
    openai_key = _apim_subscription_key(require_env("APIM_OPENAI_SUBSCRIPTION_RESOURCE_ID"))

    # Store the key as an ACA secret and reference it from an env var so it
    # never lands in template metadata.
    subprocess.run(
        [AZ, "containerapp", "secret", "set",
         "--name", container_app_name,
         "--resource-group", rg,
         "--secrets", f"apim-openai-key={openai_key}"],
        check=True, encoding="utf-8", errors="replace",
    )

    # Build the env as a dict so per-scenario ``extra_env`` cleanly overrides
    # the shared defaults (e.g. scenario 03 sends a MAF-specific
    # MODEL_DEPLOYMENT_NAME that must win over the global default) - emitting a
    # duplicate ``KEY=`` to ``--set-env-vars`` is fragile.
    env_map = {
        "AZURE_OPENAI_ENDPOINT": apim_openai_url,
        "AZURE_OPENAI_API_KEY": "secretref:apim-openai-key",
        "AZURE_OPENAI_API_VERSION": api_version,
    }
    if model_deployment:
        env_map["MODEL_DEPLOYMENT_NAME"] = model_deployment
    env_map.update(extra_env or {})
    env_args = [f"{key}={value}" for key, value in env_map.items()]

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
    """Create/update a CustomKeys Foundry project connection via the ARM control plane.

    The data-plane ``AIProjectClient.connections`` surface is read-only in
    azure-ai-projects 2.1.0 (get/list only), so the connection is PUT through
    ARM (``Microsoft.CognitiveServices/accounts/projects/connections``). Best
    effort: a failure here is logged but does not abort the deploy, since the
    agent already runs on ACA behind APIM. Returns the connection target URL.
    """
    apim_gw = require_env("APIM_GATEWAY_URL")
    project_endpoint = require_env("AZURE_AI_PROJECT_ENDPOINT")
    sub = require_env("AZURE_SUBSCRIPTION_ID")
    rg = require_env("AZURE_RESOURCE_GROUP")

    print("\n--- Step 3: Foundry project connection ---")
    endpoint_url = f"{apim_gw.rstrip('/')}/agents/{subroute.strip('/')}"
    agents_key = _apim_subscription_key(require_env("APIM_AGENTS_SUBSCRIPTION_RESOURCE_ID"))

    # Parse account + project from https://<account>.services.ai.azure.com/api/projects/<project>
    parsed = urlparse(project_endpoint)
    account = (parsed.hostname or "").split(".")[0]
    project = parsed.path.rstrip("/").split("/")[-1]
    conn_id = (
        f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices"
        f"/accounts/{account}/projects/{project}/connections/{connection_name}"
    )
    uri = f"https://management.azure.com{conn_id}?api-version=2025-04-01-preview"
    body = {
        "properties": {
            "category": "CustomKeys",
            "target": endpoint_url,
            "authType": "CustomKeys",
            "isSharedToAll": True,
            "credentials": {"keys": {"Ocp-Apim-Subscription-Key": agents_key}},
            "metadata": metadata or {},
        },
    }
    result = subprocess.run(
        [AZ, "rest", "--method", "put", "--uri", uri,
         "--headers", "Content-Type=application/json",
         "--body", json.dumps(body)],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        print(
            f"  [warn] connection {connection_name} could not be created: "
            f"{(result.stderr or result.stdout or '').strip()[:300]}",
            file=sys.stderr,
        )
    else:
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

        # A 200 response can still carry an error envelope (server_error) or an
        # empty body while the ACA replica is still warming up. Only a response
        # that actually has output counts as success.
        if getattr(response, "output", None):
            print(f"\nAssistant: {response.output_text}")
            return

        extra = getattr(response, "model_extra", None) or {}
        err = getattr(response, "error", None)
        if err is not None:
            detail = f"{getattr(err, 'code', '?')}: {getattr(err, 'message', err)}"
        elif extra.get("code") or extra.get("message"):
            detail = f"{extra.get('code')}: {extra.get('message')}"
        else:
            detail = f"status={getattr(response, 'status', None)!r}, no output"

        if attempt < max_attempts - 1:
            print(".", end="", flush=True)
            time.sleep(5)
            continue
        print(f"\n[smoke test] agent returned no output -> {detail}", file=sys.stderr)
        return
