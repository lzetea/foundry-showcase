"""
Cleanup — Delete the Contoso Travel prompt agent and all its versions.

Run this after the demo to remove server-side resources.
"""

from agents.shared.config import get_clients

from .agent_def import AGENT_NAME


def main():
    project_client, _ = get_clients()

    print(f"Deleting agent: {AGENT_NAME}")
    try:
        project_client.agents.delete(agent_name=AGENT_NAME)
        print(f"  Deleted all versions of {AGENT_NAME}")
    except Exception as e:
        if "not found" in str(e).lower():
            print(f"  Agent {AGENT_NAME} not found (already deleted?)")
        else:
            print(f"  Error: {e}")


if __name__ == "__main__":
    main()
