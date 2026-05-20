"""Scenario 03 teardown — reverses what ``deploy_and_register.py`` did.

* Deletes the Foundry project connection
  ``contoso-travel-multiagent-endpoint``.
* Rolls the ACA app ``ca-maf-agent`` back to the public placeholder
  image and strips the APIM env vars and secret.

The ACA app itself is **not** deleted — it is provisioned by Bicep and is
expected to stay put so the APIM backend wiring remains stable. To tear
the whole scenario down run ``azd down`` from the repo root (warning:
``azd down`` deletes the entire resource group).
"""

from __future__ import annotations

from agents.shared.aca_connection import (
    delete_foundry_connection,
    rollback_container_app,
)
from agents.shared.config import get_clients

from .scenario import CONNECTION_NAME, CONTAINER_APP_NAME


def main() -> None:
    print("=" * 70)
    print("Scenario 03 — teardown")
    print("=" * 70)

    project_client, _ = get_clients()
    delete_foundry_connection(project_client, CONNECTION_NAME)
    rollback_container_app(CONTAINER_APP_NAME)

    print("\nDone. Run `python -m agents.03_multi_agent.deploy_and_register`")
    print("to redeploy.")


if __name__ == "__main__":
    main()
