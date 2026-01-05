"""
Helper script to query AI agents about transcripts.

Usage:
    python query_agent.py <topic> <question>

Example:
    python query_agent.py team-meeting "What were the main action items?"
"""

import os
import sys
import argparse
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()


def query_agent(topic: str, question: str):
    """Query an AI agent about transcripts."""
    
    ai_foundry_endpoint = os.getenv("AI_FOUNDRY_ENDPOINT")
    
    if not ai_foundry_endpoint:
        raise ValueError("AI_FOUNDRY_ENDPOINT must be set in .env")
    
    # Initialize AI Foundry client with DefaultAzureCredential
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=ai_foundry_endpoint,
        credential=credential
    )
    
    # Find agent by topic
    agent_name = f"transcript-agent-{topic}"
    agent = None
    
    print(f"Looking for agent: {agent_name}")
    
    try:
        agents = project_client.agents.list_agents()
        for existing_agent in agents:
            if existing_agent.name == agent_name:
                agent = existing_agent
                print(f"✓ Found agent: {agent.id}")
                break
    except Exception as e:
        print(f"Error listing agents: {e}")
        sys.exit(1)
    
    if not agent:
        print(f"✗ No agent found for topic '{topic}'")
        print(f"\nAvailable agents:")
        try:
            agents = project_client.agents.list_agents()
            for a in agents:
                if a.name.startswith("transcript-agent-"):
                    topic_name = a.name.replace("transcript-agent-", "")
                    print(f"  - {topic_name}")
        except:
            pass
        sys.exit(1)
    
    # Create a thread and run
    print(f"\nQuestion: {question}")
    print("\nThinking...\n")
    
    thread = project_client.agents.create_thread()
    
    # Add message to thread
    project_client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=question
    )
    
    # Run the agent
    run = project_client.agents.create_and_process_run(
        thread_id=thread.id,
        assistant_id=agent.id
    )
    
    # Get messages
    messages = project_client.agents.list_messages(thread_id=thread.id)
    
    # Display response (most recent assistant message)
    for message in messages:
        if message.role == "assistant":
            for content in message.content:
                if hasattr(content, 'text'):
                    print(f"Answer:\n{content.text.value}\n")
                    
                    # Show citations if available
                    if hasattr(content.text, 'annotations') and content.text.annotations:
                        print("Sources:")
                        for annotation in content.text.annotations:
                            if hasattr(annotation, 'file_citation'):
                                print(f"  - {annotation.file_citation.file_id}")
            break


def main():
    parser = argparse.ArgumentParser(description="Query AI agent about transcripts")
    parser.add_argument("topic", help="Topic name (agent identifier)")
    parser.add_argument("question", help="Question to ask about the transcripts")
    
    args = parser.parse_args()
    
    try:
        query_agent(args.topic, args.question)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
