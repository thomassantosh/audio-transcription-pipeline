"""
Helper script to upload audio files to Azure Blob Storage with metadata.

Usage:
    python upload_audio.py <audio_file_path> [--diarization] [--topic TOPIC]

Example:
    python upload_audio.py meeting.mp3 --diarization --topic "project-planning"
"""

import os
import sys
import argparse
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()


def upload_audio(file_path: str, enable_diarization: bool = False, topic: str = "default"):
    """Upload audio file to Azure Blob Storage with metadata."""
    
    storage_conn_string = os.getenv("STORAGE_CONNECTION_STRING")
    audio_container = os.getenv("AUDIO_CONTAINER", "audio")
    
    if not storage_conn_string:
        raise ValueError("STORAGE_CONNECTION_STRING not found in environment")
    
    # Initialize blob service client
    blob_service_client = BlobServiceClient.from_connection_string(storage_conn_string)
    
    # Get blob name from file path
    blob_name = os.path.basename(file_path)
    
    # Get blob client
    blob_client = blob_service_client.get_blob_client(
        container=audio_container,
        blob=blob_name
    )
    
    # Prepare metadata
    metadata = {
        "diarization": str(enable_diarization).lower(),
        "topic": topic
    }
    
    # Upload file
    print(f"Uploading {file_path} to {audio_container}/{blob_name}")
    print(f"Metadata: {metadata}")
    
    with open(file_path, "rb") as data:
        blob_client.upload_blob(data, overwrite=True, metadata=metadata)
    
    print(f"✓ Upload complete: {blob_client.url}")


def main():
    parser = argparse.ArgumentParser(description="Upload audio file to Azure for transcription")
    parser.add_argument("file_path", help="Path to audio file")
    parser.add_argument("--diarization", action="store_true", 
                       help="Enable speaker diarization")
    parser.add_argument("--topic", default="default",
                       help="Topic name for agent grouping (default: 'default')")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file_path):
        print(f"Error: File not found: {args.file_path}")
        sys.exit(1)
    
    try:
        upload_audio(args.file_path, args.diarization, args.topic)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
