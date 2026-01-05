"""
Azure Functions for audio transcription and AI agent integration.

Functions:
1. audio_blob_trigger: Triggered when audio files are uploaded to 'audio' container
2. transcript_blob_trigger: Triggered when transcripts are uploaded to 'transcripts' container
"""

import os
import json
import logging
import time
import azure.functions as func
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

# Initialize function app
app = func.FunctionApp()

# Environment variables
SPEECH_KEY = os.environ.get("SPEECH_KEY")
SPEECH_REGION = os.environ.get("SPEECH_REGION")
AI_FOUNDRY_ENDPOINT = os.environ.get("AI_FOUNDRY_ENDPOINT")
STORAGE_CONNECTION_STRING = os.environ.get("STORAGE_CONNECTION_STRING")
AUDIO_CONTAINER = os.environ.get("AUDIO_CONTAINER", "audio")
TRANSCRIPTS_CONTAINER = os.environ.get("TRANSCRIPTS_CONTAINER", "transcripts")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def create_batch_transcription(audio_blob_url: str, enable_diarization: bool = False) -> str:
    """
    Create a batch transcription job using Azure Speech Service.
    
    Args:
        audio_blob_url: URL to the audio file in blob storage
        enable_diarization: Whether to enable speaker diarization
        
    Returns:
        Transcription ID
    """
    import requests
    
    # Speech Service REST API endpoint
    base_url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2"
    transcription_url = f"{base_url}/transcriptions"
    
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": "application/json"
    }
    
    # Configure transcription request
    transcription_definition = {
        "contentUrls": [audio_blob_url],
        "properties": {
            "diarizationEnabled": enable_diarization,
            "wordLevelTimestampsEnabled": True,
            "punctuationMode": "DictatedAndAutomatic",
            "profanityFilterMode": "Masked"
        },
        "locale": "en-US",
        "displayName": f"Transcription_{time.time()}"
    }
    
    response = requests.post(transcription_url, headers=headers, json=transcription_definition)
    response.raise_for_status()
    
    transcription_data = response.json()
    transcription_id = transcription_data["self"].split("/")[-1]
    
    logger.info(f"Created transcription job: {transcription_id}")
    return transcription_id


def poll_transcription_status(transcription_id: str, max_wait_seconds: int = 600) -> dict:
    """
    Poll transcription status until completed or failed.
    
    Args:
        transcription_id: ID of the transcription job
        max_wait_seconds: Maximum time to wait for completion
        
    Returns:
        Transcription result data
    """
    import requests
    
    base_url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2"
    status_url = f"{base_url}/transcriptions/{transcription_id}"
    
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY
    }
    
    start_time = time.time()
    
    while time.time() - start_time < max_wait_seconds:
        response = requests.get(status_url, headers=headers)
        response.raise_for_status()
        
        status_data = response.json()
        status = status_data["status"]
        
        logger.info(f"Transcription status: {status}")
        
        if status == "Succeeded":
            # Get transcription files
            files_url = f"{status_url}/files"
            files_response = requests.get(files_url, headers=headers)
            files_response.raise_for_status()
            
            files_data = files_response.json()
            
            # Find the transcription result file
            for file_info in files_data["values"]:
                if file_info["kind"] == "Transcription":
                    result_url = file_info["links"]["contentUrl"]
                    result_response = requests.get(result_url)
                    result_response.raise_for_status()
                    return result_response.json()
            
            raise Exception("Transcription file not found")
        
        elif status == "Failed":
            raise Exception(f"Transcription failed: {status_data}")
        
        time.sleep(10)
    
    raise Exception(f"Transcription timeout after {max_wait_seconds} seconds")


@app.blob_trigger(arg_name="audioBlob", 
                  path="audio/{name}",
                  connection="STORAGE_CONNECTION_STRING")
def audio_blob_trigger(audioBlob: func.InputStream):
    """
    Triggered when an audio file is uploaded to the audio container.
    Creates a batch transcription job and saves result to transcripts container.
    
    Blob metadata:
    - diarization: 'true' or 'false' to enable/disable speaker diarization
    - topic: Optional topic name for agent grouping (default: 'default')
    """
    logger.info(f"Audio blob trigger: {audioBlob.name}")
    
    try:
        # Get blob metadata
        blob_service_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
        
        # Strip container prefix from blob name if present
        blob_name = audioBlob.name
        if blob_name.startswith(f"{AUDIO_CONTAINER}/"):
            blob_name = blob_name[len(AUDIO_CONTAINER)+1:]
        
        blob_client = blob_service_client.get_blob_client(
            container=AUDIO_CONTAINER,
            blob=blob_name
        )
        
        blob_properties = blob_client.get_blob_properties()
        metadata = blob_properties.metadata or {}
        
        # Check if diarization is enabled (default: false)
        enable_diarization = metadata.get("diarization", "false").lower() == "true"
        topic = metadata.get("topic", "default")
        
        logger.info(f"Diarization enabled: {enable_diarization}, Topic: {topic}")
        
        # Generate SAS URL for the audio blob
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions
        from datetime import datetime, timedelta
        
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=AUDIO_CONTAINER,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=2)
        )
        
        audio_blob_url = f"{blob_client.url}?{sas_token}"
        
        # Create batch transcription
        transcription_id = create_batch_transcription(audio_blob_url, enable_diarization)
        
        # Poll for completion (with timeout)
        transcription_result = poll_transcription_status(transcription_id, max_wait_seconds=600)
        
        # Extract transcript text
        combined_phrases = transcription_result.get("combinedRecognizedPhrases", [])
        if not combined_phrases:
            raise Exception("No transcription results found")
        
        transcript_text = combined_phrases[0].get("display", "")
        
        # Save transcript to blob storage
        transcript_filename = blob_name.rsplit(".", 1)[0] + ".txt"
        transcript_blob_client = blob_service_client.get_blob_client(
            container=TRANSCRIPTS_CONTAINER,
            blob=transcript_filename
        )
        
        # Add metadata to transcript blob
        transcript_metadata = {
            "topic": topic,
            "source_audio": blob_name,
            "diarization": str(enable_diarization).lower(),
            "transcription_id": transcription_id
        }
        
        transcript_blob_client.upload_blob(
            transcript_text,
            overwrite=True,
            metadata=transcript_metadata
        )
        
        logger.info(f"Transcript saved: {transcript_filename}")
        
    except Exception as e:
        logger.error(f"Error processing audio blob: {str(e)}", exc_info=True)
        raise


@app.blob_trigger(arg_name="transcriptBlob",
                  path="transcripts/{name}",
                  connection="STORAGE_CONNECTION_STRING")
def transcript_blob_trigger(transcriptBlob: func.InputStream):
    """
    Triggered when a transcript is uploaded to the transcripts container.
    Creates or updates an AI agent with the transcript as knowledge.
    
    Blob metadata:
    - topic: Topic name for agent grouping (agents are reused per topic)
    """
    logger.info(f"Transcript blob trigger: {transcriptBlob.name}")
    
    try:
        # Get blob metadata
        blob_service_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
        
        # Strip container prefix from blob name if present
        blob_name = transcriptBlob.name
        if blob_name.startswith(f"{TRANSCRIPTS_CONTAINER}/"):
            blob_name = blob_name[len(TRANSCRIPTS_CONTAINER)+1:]
        
        blob_client = blob_service_client.get_blob_client(
            container=TRANSCRIPTS_CONTAINER,
            blob=blob_name
        )
        
        blob_properties = blob_client.get_blob_properties()
        metadata = blob_properties.metadata or {}
        topic = metadata.get("topic", "default")
        
        logger.info(f"Processing transcript for topic: {topic}")
        
        # Initialize AI Projects client
        # Note: DefaultAzureCredential will use managed identity in Azure Functions
        credential = DefaultAzureCredential()
        project_client = AIProjectClient(
            endpoint=AI_FOUNDRY_ENDPOINT,
            credential=credential
        )
        
        # Read transcript content and save to temp file
        import tempfile
        transcript_content = transcriptBlob.read().decode('utf-8')
        
        # Save to temporary file for upload
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp_file:
            tmp_file.write(transcript_content)
            temp_file_path = tmp_file.name
        
        try:
            # Upload file and create vector store
            from azure.ai.agents.models import FilePurpose, FileSearchTool
            
            file = project_client.agents.files.upload_and_poll(
                file_path=temp_file_path,
                purpose=FilePurpose.AGENTS
            )
            logger.info(f"Uploaded file, file ID: {file.id}")
            
            # Create vector store with the uploaded file
            vector_store = project_client.agents.vector_stores.create_and_poll(
                file_ids=[file.id],
                name=f"transcripts-{topic}"
            )
            logger.info(f"Created vector store, ID: {vector_store.id}")
            
            # Create file search tool
            file_search = FileSearchTool(vector_store_ids=[vector_store.id])
            
            # Check if agent exists for this topic (list agents and find by name)
            agent_name = f"transcript-agent-{topic}"
            agent = None
            
            try:
                # List all agents and find matching name
                agents_list = list(project_client.agents.list())
                for existing_agent in agents_list:
                    if hasattr(existing_agent, 'name') and existing_agent.name == agent_name:
                        agent = existing_agent
                        logger.info(f"Found existing agent: {agent.id}")
                        
                        # Update existing agent with new vector store
                        project_client.agents.update_agent(
                            agent_id=agent.id,
                            tools=file_search.definitions,
                            tool_resources=file_search.resources
                        )
                        logger.info(f"Updated agent {agent.id} with new vector store")
                        break
            except Exception as e:
                logger.info(f"Error checking for existing agent: {str(e)}")
            
            # Create agent if doesn't exist
            if not agent:
                logger.info(f"Creating new agent: {agent_name}")
                agent = project_client.agents.create_agent(
                    model="gpt-4o-mini",
                    name=agent_name,
                    instructions=f"You are a helpful assistant that answers questions about transcripts related to the topic: {topic}. "
                                f"Use the provided transcript files to answer user questions accurately and cite specific parts of the transcript when relevant.",
                    tools=file_search.definitions,
                    tool_resources=file_search.resources
                )
                logger.info(f"Created agent: {agent.id}")
        
        finally:
            # Clean up temp file
            import os
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
        
        logger.info(f"Successfully processed transcript for agent {agent.id}")
        
    except Exception as e:
        logger.error(f"Error processing transcript blob: {str(e)}", exc_info=True)
        raise
