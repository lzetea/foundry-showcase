"""Scenario 04 teardown — deletes the agent, vector store, and uploaded files.

``project_client.agents.delete`` cascades across every version, so we don't
need to iterate versions manually.
"""

from agents.shared.config import get_clients

from .agent_def import AGENT_NAME, delete_vector_store


def main() -> None:
    project_client, openai_client = get_clients()

    try:
        project_client.agents.delete(agent_name=AGENT_NAME)
        print(f"  [deleted] agent {AGENT_NAME} (all versions)")
    except Exception as exc:
        if "not found" in str(exc).lower():
            print(f"  [skip] agent {AGENT_NAME} not found (already deleted?)")
        else:
            print(f"  [warn] agent {AGENT_NAME} could not be deleted: {exc}")

    delete_vector_store(openai_client)


if __name__ == "__main__":
    main()
