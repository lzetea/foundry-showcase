"""Scenario 04 — create and smoke-test the Foundry built-in tools agent.

No container. No function-tool dispatch loop. All tool execution is done
server-side by Foundry: file search hits the vector store, code interpreter
runs a sandboxed Python process, bing grounding hits Bing.
"""

from agents.shared.config import MODEL_NAME, get_clients

from .agent_def import AGENT_NAME, get_or_create_agent


DEMO_QUERIES = [
    # Triggers file_search.
    "I'm flying Business to Tokyo with Contoso. How many bags can I check and what's the weight limit?",
    # Triggers code_interpreter + file_search.
    "I have 62,000 Contoso Elite miles. What's the most expensive Business-class transatlantic award I can book, and how many miles would I have left?",
    # Triggers file_search + possibly bing_grounding if configured.
    "I'm a US passport holder flying to Saudi Arabia next month. What documentation do I need, and is there anything I should know about current entry requirements?",
]


def main() -> None:
    project_client, openai_client = get_clients()

    print("Creating Contoso Travel Foundry-tools agent ...")
    agent = get_or_create_agent(project_client, openai_client, MODEL_NAME)
    print(f"  Agent: {agent.name} v{agent.version}")

    for query in DEMO_QUERIES:
        print(f"\n{'=' * 70}\nUser: {query}\n{'=' * 70}")

        conversation = openai_client.conversations.create()
        try:
            response = openai_client.responses.create(
                conversation=conversation.id,
                extra_body={
                    "agent_reference": {
                        "name": agent.name,
                        "type": "agent_reference",
                    }
                },
                input=query,
            )
            print(f"\nAssistant: {response.output_text}")
            if response.usage is not None:
                print(f"  Tokens: {response.usage}")
        finally:
            openai_client.conversations.delete(conversation.id)

    print(f"\n{'=' * 70}")
    print(f"Agent registered: {agent.name} v{agent.version}")
    print("Use the shared scripts:")
    print("  python -m agents.shared.trace    --scenario 04_foundry_tools_agent")
    print("  python -m agents.shared.evaluate --scenario 04_foundry_tools_agent")
    print("  python -m agents.shared.redteam  --scenario 04_foundry_tools_agent")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
