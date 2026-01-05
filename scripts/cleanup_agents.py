#!/usr/bin/env python3
"""
Cleanup script to delete all agents and threads from Azure AI Foundry.

This script removes all agents and threads from the configured Azure AI
Foundry project and cleans up the local .env file.

Usage:
    python scripts/cleanup_agents.py
"""

import os
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv, find_dotenv

# Load .env from current dir or parent directories
load_dotenv(find_dotenv(usecwd=True))


def get_env_file_path() -> Path:
    """Get the path to the .env file at the project root."""
    env_file = find_dotenv(usecwd=True)
    if env_file:
        return Path(env_file)
    return Path.cwd() / ".env"


def remove_agent_ids_from_env() -> bool:
    """Remove all agent IDs from the .env file."""
    env_file = get_env_file_path()
    
    if not env_file.exists():
        return False
    
    try:
        with open(env_file, "r") as f:
            lines = f.readlines()
        
        # Filter out lines that look like agent IDs
        agent_vars = ["EMPLOYEE_AGENT_ID"]
        new_lines = [
            line for line in lines 
            if not any(line.startswith(f"{var}=") for var in agent_vars)
        ]
        
        if len(new_lines) < len(lines):
            with open(env_file, "w") as f:
                f.writelines(new_lines)
            return True
        return False
    except Exception as e:
        print(f"⚠️  Could not clean .env file: {e}")
        return False


def delete_all_threads(agents_client):
    """Delete all threads from the Azure AI Foundry project."""
    print("\n📋 Listing all threads...")
    
    try:
        # Try to list threads - this may not be supported in all SDK versions
        threads_iterator = agents_client.threads.list()
        threads = list(threads_iterator)
        
        if not threads:
            print("✓ No threads found")
            return 0
        
        print(f"\nFound {len(threads)} thread(s):")
        for thread in threads:
            thread_id = getattr(thread, 'id', str(thread))
            print(f"  - Thread ID: {thread_id}")
        
        print(f"\n🗑️  Deleting {len(threads)} thread(s)...")
        deleted_count = 0
        for thread in threads:
            thread_id = getattr(thread, 'id', str(thread))
            try:
                agents_client.threads.delete(thread_id)
                print(f"  ✓ Deleted thread: {thread_id}")
                deleted_count += 1
            except Exception as e:
                print(f"  ✗ Failed to delete thread {thread_id}: {e}")
        
        return deleted_count
    except AttributeError:
        print("⚠️  Thread listing not supported in this SDK version")
        return 0
    except Exception as e:
        print(f"⚠️  Could not list threads: {e}")
        return 0


def delete_all_agents(agents_client):
    """Delete all agents from the Azure AI Foundry project."""
    print("\n📋 Listing all agents...")
    
    agents = []
    try:
        # Try different SDK method names based on version
        if hasattr(agents_client, 'list_agents'):
            agents = list(agents_client.list_agents())
        elif hasattr(agents_client, 'list'):
            agents = list(agents_client.list())
        else:
            # Fallback: try to get available methods
            available = [m for m in dir(agents_client) if not m.startswith('_')]
            print(f"⚠️  Available methods: {', '.join(available[:15])}...")
            return 0
    except Exception as e:
        print(f"⚠️  Could not list agents: {e}")
        return 0
    
    if not agents:
        print("✓ No agents found")
        return 0
    
    print(f"\nFound {len(agents)} agent(s):")
    for agent in agents:
        agent_name = getattr(agent, 'name', 'Unknown')
        agent_id = getattr(agent, 'id', str(agent))
        print(f"  - {agent_name} (ID: {agent_id})")
    
    print(f"\n🗑️  Deleting {len(agents)} agent(s)...")
    deleted_count = 0
    for agent in agents:
        agent_name = getattr(agent, 'name', 'Unknown')
        agent_id = getattr(agent, 'id', str(agent))
        try:
            agents_client.delete_agent(agent_id)
            print(f"  ✓ Deleted: {agent_name} ({agent_id})")
            deleted_count += 1
        except Exception as e:
            print(f"  ✗ Failed to delete {agent_name}: {e}")
    
    return deleted_count


def cleanup_all():
    """Delete all agents and threads from the Azure AI Foundry project."""
    # Use AI_FOUNDRY_ENDPOINT (the full project endpoint)
    project_endpoint = os.getenv("AI_FOUNDRY_ENDPOINT")
    
    if not project_endpoint:
        print("❌ AI_FOUNDRY_ENDPOINT environment variable is required")
        print("   Run 'make get-output' to generate the .env file first.")
        sys.exit(1)
    
    print("=" * 60)
    print("🧹 Azure AI Foundry Cleanup")
    print("=" * 60)
    print(f"\n🔗 Connecting to: {project_endpoint}")
    
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential()
    )
    
    try:
        agents_client = project_client.agents
        
        # Delete threads first (they reference agents)
        threads_deleted = delete_all_threads(agents_client)
        
        # Then delete agents
        agents_deleted = delete_all_agents(agents_client)
        
        # Clean up agent IDs from .env file
        env_cleaned = remove_agent_ids_from_env()
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 Cleanup Summary")
        print("=" * 60)
        print(f"  Threads deleted:       {threads_deleted}")
        print(f"  Agents deleted:        {agents_deleted}")
        print(f"  .env file cleaned:     {'Yes' if env_cleaned else 'No (no agent IDs found)'}")
        print("=" * 60)
        print("\n✅ Cleanup complete")
        
    except Exception as e:
        print(f"\n❌ Cleanup failed: {e}")
        sys.exit(1)
    finally:
        project_client.close()


if __name__ == "__main__":
    cleanup_all()
