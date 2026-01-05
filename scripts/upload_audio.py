"""
Helper script to upload audio files to Azure Blob Storage with metadata.

Usage:
    python upload_audio.py <audio_file_path> [--diarization] [--topic TOPIC]

Example:
    python upload_audio.py meeting.mp3 --diarization --topic "project-planning"
"""

import os
import sys
import time
import argparse
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

# Supported audio formats for Azure Speech Service Batch Transcription
SUPPORTED_FORMATS = {'.wav', '.mp3', '.ogg', '.opus', '.flac', '.amr', '.webm'}


def create_progress_callback(file_size: int):
    """Create a progress callback for blob upload."""
    uploaded = {'bytes': 0}
    
    def progress_callback(current, total):
        # Azure SDK passes (current_bytes, total_bytes)
        bytes_transferred = current
        if total and total > 0:
            file_size_actual = total
        else:
            file_size_actual = file_size
        
        percent = (bytes_transferred / file_size_actual) * 100
        bar_length = 40
        filled = int(bar_length * bytes_transferred // file_size_actual)
        bar = '█' * filled + '░' * (bar_length - filled)
        mb_transferred = bytes_transferred / (1024 * 1024)
        mb_total = file_size_actual / (1024 * 1024)
        sys.stdout.write(f'\r  Uploading: |{bar}| {percent:.1f}% ({mb_transferred:.1f}/{mb_total:.1f} MB)')
        sys.stdout.flush()
        if bytes_transferred >= file_size_actual:
            print()  # New line when complete
    
    return progress_callback


def upload_audio(file_path: str, enable_diarization: bool = False, topic: str = "default"):
    """Upload audio file to Azure Blob Storage with metadata."""
    
    # Validate file format
    file_ext = os.path.splitext(file_path)[1].lower()
    if file_ext not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported audio format: '{file_ext}'\n"
            f"Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}\n"
            f"Tip: Convert m4a to mp3 with: make convert-audio INPUT=file.m4a OUTPUT=file.mp3"
        )
    
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
    
    # Check if blob exists and delete it first to ensure clean state
    if blob_client.exists():
        print(f"Deleting existing blob to clear all metadata...")
        blob_client.delete_blob()
        time.sleep(5) # Wait for 5 seconds to propagate deletion before re-uploading
    
    # Get file size for progress tracking
    file_size = os.path.getsize(file_path)
    
    # Upload file with progress callback
    print(f"Uploading {file_path} to {audio_container}/{blob_name}")
    print(f"Metadata: {metadata}")
    
    progress_callback = create_progress_callback(file_size)
    
    with open(file_path, "rb") as data:
        blob_client.upload_blob(
            data, 
            overwrite=True, 
            metadata=metadata,
            progress_hook=progress_callback
        )
    
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
