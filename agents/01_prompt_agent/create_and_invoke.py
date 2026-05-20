"""
Step 1A — Create and invoke a Prompt Agent with function tools.

This script is the one place that **bumps the agent version**. All other
scripts (``scenario.py`` used by trace/evaluate/redteam) reuse whatever
version this script last created.

Run ``cleanup.py`` after the demo to delete the agent and every version.
"""

from agents.shared.config import MODEL_NAME, get_clients

from .agent_def import AGENT_NAME, get_or_create_agent, run_tool_loop


TEST_QUERIES = [
    "What flights are available from Seattle to Paris?",
    "Find me a 5-star hotel in Tokyo with a hot spring.",
    "Plan a trip from Chicago to Rome — I need flights, hotel, and a car rental.",
]


def main() -> None:
    project_client, openai_client = get_clients()

    print("Creating Contoso Travel prompt agent ...")
    agent = get_or_create_agent(project_client, MODEL_NAME)
    print(f"  Agent: {agent.name} (version {agent.version})")

    for query in TEST_QUERIES:
        print(f"\n{'=' * 70}\nUser: {query}\n{'=' * 70}")
        conversation = openai_client.conversations.create()
        try:
            answer = run_tool_loop(
                openai_client,
                agent_name=agent.name,
                conversation_id=conversation.id,
                query=query,
                verbose=True,
            )
            print(f"\nAssistant: {answer}")
        finally:
            openai_client.conversations.delete(conversation.id)

    print(f"\n{'=' * 70}")
    print(f"Agent: {agent.name} v{agent.version}")
    print("This version is reused by trace.py, evaluate.py, and redteam.py.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
