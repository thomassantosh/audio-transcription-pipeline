"""
Azure Functions for audio transcription and AI agent integration.

Clean workflow:
1. audio_blob_trigger: Upload audio → Start batch transcription with destinationContainerUrl
2. Speech Service writes JSON result directly to transcripts container
3. transcript_blob_trigger: New transcript JSON → Parse, create .txt, update AI agent in Foundry

Correlation ID flows through all stages for end-to-end tracing in Application Insights.
"""

import os
import time
import logging
import uuid
from datetime import datetime, timedelta
import azure.functions as func
from azure.storage.blob import BlobServiceClient, generate_blob_sas, generate_container_sas, BlobSasPermissions, ContainerSasPermissions
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
import requests

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

def validate_environment_variables():
    """Validate required environment variables are set."""
    required_vars = {
        "SPEECH_KEY": SPEECH_KEY,
        "SPEECH_REGION": SPEECH_REGION,
        "AI_FOUNDRY_ENDPOINT": AI_FOUNDRY_ENDPOINT,
        "STORAGE_CONNECTION_STRING": STORAGE_CONNECTION_STRING
    }
    
    missing_vars = [var_name for var_name, var_value in required_vars.items() if not var_value]
    
    if missing_vars:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing_vars)}. "
            "Please configure these in local.settings.json (local) or App Settings (Azure)."
        )

# Validate environment variables at startup
validate_environment_variables()

def is_local() -> bool:
    """ Returns True when running locally (func start / pytest / script), False when running in Azure. """
    return not os.environ.get("WEBSITE_HOSTNAME")

def get_correlation_id(context=None, metadata=None):
    """Generate or retrieve correlation ID for tracking requests across functions."""
    # Try to get from metadata first
    if metadata and "correlation_id" in metadata:
        return metadata["correlation_id"]
    # Try to get from context
    if context and hasattr(context, 'invocation_id'):
        return str(context.invocation_id)
    # Generate new one
    return str(uuid.uuid4())


def log_with_correlation(logger_instance, level, message, correlation_id, **kwargs):
    """Log message with correlation ID for Application Insights tracking."""
    enriched_message = f"[CorrelationID: {correlation_id}] {message}"
    log_func = getattr(logger_instance, level)
    log_func(enriched_message, **kwargs)


def create_batch_transcription(
    audio_blob_url: str,
    destination_container_url: str | None,
    audio_blob_name: str,
    topic: str,
    correlation_id: str,
    enable_diarization: bool = False
) -> str:
    """
    Create a batch transcription job using Azure Speech Service.

    Args:
        audio_blob_url: SAS URL to the audio file in blob storage
        destination_container_url: SAS URL for Speech Service to write results (with write permission)
        audio_blob_name: Original audio blob name (stored in customProperties for mapping)
        topic: Topic for agent grouping (stored in customProperties)
        correlation_id: Correlation ID for tracking
        enable_diarization: Whether to enable speaker diarization

    Returns:
        Transcription ID
    """
    base_url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2"
    transcription_url = f"{base_url}/transcriptions"

    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": "application/json"
    }

    # Configure transcription request
    transcription_properties = {
        "diarizationEnabled": enable_diarization,
        "wordLevelTimestampsEnabled": True,
        "punctuationMode": "DictatedAndAutomatic",
        "profanityFilterMode": "Masked",
    }
    
    # Use destinationContainerUrl for Speech Service to write results directly
    if destination_container_url:
        transcription_properties["destinationContainerUrl"] = destination_container_url
        log_with_correlation(logger, "info", 
            f"Using destinationContainerUrl for results (Speech Service will write directly)", 
            correlation_id)
    
    transcription_definition = {
        "contentUrls": [audio_blob_url],
        "properties": transcription_properties,
        "locale": "en-US",
        "displayName": f"Transcription_{datetime.utcnow().isoformat()}",
        "description": correlation_id,
        # Store audio filename and topic in customProperties for mapping back
        "customProperties": {
            "audioFileName": audio_blob_name,
            "topic": topic,
            "correlationId": correlation_id
        }
    }

    response = requests.post(transcription_url, headers=headers, json=transcription_definition)
    response.raise_for_status()

    transcription_data = response.json()
    transcription_id = transcription_data["self"].split("/")[-1]

    log_with_correlation(logger, "info", f"Created transcription job: {transcription_id}", correlation_id)
    return transcription_id

def get_transcription_status(transcription_id: str) -> dict:
    """
    Fetches the current status of a Speech batch transcription.

    Returns the JSON payload from:
      GET /speechtotext/v3.2/transcriptions/{id}

    Expected keys include:
      - "status": "NotStarted" | "Running" | "Succeeded" | "Failed"
      - "properties": may include "error"
      - "contentUrls"
      - etc.
    """
    if not SPEECH_KEY or not SPEECH_REGION:
        raise RuntimeError("SPEECH_KEY and/or SPEECH_REGION not set")

    base_url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2"
    url = f"{base_url}/transcriptions/{transcription_id}"

    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()

def handle_transcription_completed(
    transcription_id: str,
    correlation_id: str,
):
    """
    Shared completion handler for:
    - webhook callbacks (Azure)
    - polling (local dev)

    Fetches transcription result and saves transcript blob.
    """

    base_url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2"
    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}

    # ---- Get transcription files ----
    files_url = f"{base_url}/transcriptions/{transcription_id}/files"
    files_response = requests.get(files_url, headers=headers)
    files_response.raise_for_status()
    files_data = files_response.json()

    transcript_text = None

    for file_info in files_data.get("values", []):
        if file_info.get("kind") == "Transcription":
            result_url = file_info["links"]["contentUrl"]
            result_response = requests.get(result_url)
            result_response.raise_for_status()

            transcription_result = result_response.json()
            combined_phrases = transcription_result.get("combinedRecognizedPhrases", [])

            if combined_phrases:
                transcript_text = combined_phrases[0].get("display", "")
            break

    if not transcript_text:
        raise RuntimeError("No transcription text found")

    # ---- Resolve original audio blob ----
    transcription_response = requests.get(
        f"{base_url}/transcriptions/{transcription_id}",
        headers=headers
    )
    transcription_response.raise_for_status()
    transcription_data = transcription_response.json()

    content_url = transcription_data.get("contentUrls", [None])[0]
    if not content_url:
        raise RuntimeError("Cannot determine source audio blob")

    blob_name = content_url.split(f"/{AUDIO_CONTAINER}/")[1].split("?")[0]

    audio_blob_client = blob_service_client.get_blob_client(
        container=AUDIO_CONTAINER,
        blob=blob_name
    )

    audio_metadata = audio_blob_client.get_blob_properties().metadata or {}
    topic = audio_metadata.get("topic", "default")

    # ---- Save transcript ----
    transcript_filename = blob_name.rsplit(".", 1)[0] + ".txt"
    transcript_blob_client = blob_service_client.get_blob_client(
        container=TRANSCRIPTS_CONTAINER,
        blob=transcript_filename
    )

    transcript_metadata = {
        "topic": topic,
        "source_audio": blob_name,
        "transcription_id": transcription_id,
        "correlation_id": correlation_id,
    }

    transcript_blob_client.upload_blob(
        transcript_text,
        overwrite=True,
        metadata=transcript_metadata
    )

    log_with_correlation(
        logger,
        "info",
        f"✅ Transcript saved: {transcript_filename}",
        correlation_id
    )

def handle_transcription_failed(
    transcription_id: str,
    correlation_id: str,
):
    """
    Shared failure handler for:
    - webhook callbacks
    - local polling

    Records failure details and marks the source audio blob accordingly.
    """

    log_with_correlation(
        logger,
        "error",
        f"❌ Handling transcription failure: {transcription_id}",
        correlation_id
    )

    base_url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2"
    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}

    # Try to get detailed error info
    error_message = "Unknown transcription failure"

    try:
        transcription_response = requests.get(
            f"{base_url}/transcriptions/{transcription_id}",
            headers=headers
        )
        transcription_response.raise_for_status()
        transcription_data = transcription_response.json()

        properties = transcription_data.get("properties", {})
        error_info = properties.get("error")

        if error_info:
            error_message = error_info.get("message", error_message)

        content_url = transcription_data.get("contentUrls", [None])[0]
        if not content_url:
            raise RuntimeError("Cannot determine source audio blob")

        blob_name = content_url.split(f"/{AUDIO_CONTAINER}/")[1].split("?")[0]

        audio_blob_client = blob_service_client.get_blob_client(
            container=AUDIO_CONTAINER,
            blob=blob_name
        )

        # Update audio blob metadata to mark failure
        metadata = audio_blob_client.get_blob_properties().metadata or {}
        metadata.update({
            "transcription_status": "failed",
            "transcription_error": error_message,
            "correlation_id": correlation_id,
        })

        audio_blob_client.set_blob_metadata(metadata)

        log_with_correlation(
            logger,
            "error",
            f"❌ Transcription failed for blob '{blob_name}': {error_message}",
            correlation_id
        )

    except Exception as e:
        # Failure handling should NEVER crash the function
        log_with_correlation(
            logger,
            "error",
            f"❌ Error while handling transcription failure: {str(e)}",
            correlation_id,
            exc_info=True
        )


def wait_for_transcription_completion(
    transcription_id: str,
    correlation_id: str,
    poll_interval_seconds: int = 10,
    timeout_seconds: int = 10 * 60,  # 10 minutes (Azure Functions timeout)
):
    """
    Local-dev helper.
    Polls Azure Speech transcription status until completion or timeout.
    This should NEVER be used in Azure-hosted runs.
    """

    log_with_correlation(
        logger, "info",
        f"Polling transcription status (every {poll_interval_seconds}s, timeout {timeout_seconds}s)",
        correlation_id
    )

    deadline = time.time() + timeout_seconds
    last_status = None

    while time.time() < deadline:
        status_response = get_transcription_status(transcription_id)
        status = status_response.get("status")

        # Only log when status changes (noise reduction)
        if status != last_status:
            log_with_correlation(
                logger, "info",
                f"Transcription status changed → {status}",
                correlation_id
            )
            last_status = status

        if status == "Succeeded":
            log_with_correlation(
                logger, "info",
                "🎉 Transcription completed successfully",
                correlation_id
            )

            handle_transcription_completed(
                transcription_id=transcription_id,
                correlation_id=correlation_id
            )
            return

        if status == "Failed":
            log_with_correlation(
                logger, "error",
                "❌ Transcription failed",
                correlation_id
            )

            handle_transcription_failed(
                transcription_id=transcription_id,
                correlation_id=correlation_id
            )
            return

        time.sleep(poll_interval_seconds)

    # Timeout reached
    raise TimeoutError(
        f"Transcription {transcription_id} did not complete within {timeout_seconds} seconds"
    )

blob_service_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)

@app.blob_trigger(arg_name="audioBlob",
                  path="audio/{name}",
                  connection="STORAGE_CONNECTION_STRING")
def audio_blob_trigger(audioBlob: func.InputStream, context: func.Context):
    """
    Triggered when an audio file is uploaded to the audio container.
    Starts a batch transcription job with webhook callback.

    Blob metadata:
    - diarization: 'true' or 'false' to enable/disable speaker diarization
    - topic: Topic name for agent grouping (default: 'default')
    - correlation_id: Optional correlation ID (will generate if not provided)
    """

    # Get blob name without container prefix
    blob_name = audioBlob.name
    if blob_name.startswith(f"{AUDIO_CONTAINER}/"):
        blob_name = blob_name[len(AUDIO_CONTAINER)+1:]

    # Get blob metadata
    blob_client = blob_service_client.get_blob_client(container=AUDIO_CONTAINER, blob=blob_name)
    blob_properties = blob_client.get_blob_properties()
    metadata = blob_properties.metadata or {}

    # Get or generate correlation ID
    correlation_id = get_correlation_id(context, metadata)

    log_with_correlation(logger, "info", f"Metadata: {metadata}", correlation_id)
    log_with_correlation(logger, "info", f"🎵 Audio blob uploaded: {blob_name}", correlation_id)

    # Idempotency checks
    if "transcription_id" in metadata:
        existing_transcription_id = metadata["transcription_id"]
        
        # Check if transcript already exists
        transcript_filename = blob_name.rsplit(".", 1)[0] + ".txt"
        transcript_client = blob_service_client.get_blob_client(container=TRANSCRIPTS_CONTAINER, blob=transcript_filename)
        
        if transcript_client.exists():
            log_with_correlation(logger, "info", f"Transcript already exists: {transcript_filename}, skipping", correlation_id)
            return
        
        # Check if transcription is still active
        try:
            status_response = get_transcription_status(existing_transcription_id)
            status = status_response.get("status")
            
            if status in ["NotStarted", "Running"]:
                log_with_correlation(logger, "info", 
                    f"Transcription still in progress (ID: {existing_transcription_id}, status: {status}), skipping duplicate trigger", 
                    correlation_id)
                return
            elif status == "Succeeded":
                log_with_correlation(logger, "warning", 
                    f"Transcription succeeded but transcript not found yet (ID: {existing_transcription_id}), waiting...", 
                    correlation_id)
                return
            else:
                # Failed or unknown status - restart
                log_with_correlation(logger, "warning", 
                    f"Previous transcription has status '{status}' (ID: {existing_transcription_id}), restarting", 
                    correlation_id)
                # Continue to start new transcription
        except Exception as e:
            log_with_correlation(logger, "warning", 
                f"Could not check transcription status for {existing_transcription_id}: {e}, restarting", 
                correlation_id)
            # Continue to start new transcription

    try:

        # Get transcription settings from metadata
        enable_diarization = metadata.get("diarization", "false").lower() == "true"
        topic = metadata.get("topic", "default")

        log_with_correlation(logger, "info",
            f"Starting transcription - Topic: {topic}, Diarization: {enable_diarization}",
            correlation_id)

        # Generate SAS URL for audio blob (valid for 2 hours)
        # Check if credential has account_key (required for SAS generation)
        if not hasattr(blob_service_client.credential, 'account_key'):
            raise RuntimeError(
                "Storage connection string must include account key for SAS token generation. "
                "Managed identity authentication is not supported for this operation."
            )
        
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=AUDIO_CONTAINER,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=2)
        )
        audio_blob_url = f"{blob_client.url}?{sas_token}"

        # Generate destination container SAS URL for Speech Service to write results
        destination_container_url = None
        running_locally = is_local()
        
        log_with_correlation(logger, "info", 
            f"Environment check - is_local: {running_locally}", 
            correlation_id)

        if running_locally:
            # Local dev: Use polling instead of destination container
            log_with_correlation(
                logger, "warning",
                "⚠️ Local development detected: will poll for transcription completion.",
                correlation_id
            )
        else:
            # Generate container SAS with write permission for Speech Service
            container_sas_token = generate_container_sas(
                account_name=blob_service_client.account_name,
                container_name=TRANSCRIPTS_CONTAINER,
                account_key=blob_service_client.credential.account_key,
                permission=ContainerSasPermissions(read=True, write=True, list=True),
                expiry=datetime.utcnow() + timedelta(hours=4)  # 4 hours for transcription to complete
            )
            destination_container_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{TRANSCRIPTS_CONTAINER}?{container_sas_token}"
            log_with_correlation(logger, "info", 
                f"Generated destination container URL for transcripts", 
                correlation_id)

        # Create batch transcription with destination container
        transcription_id = create_batch_transcription(
            audio_blob_url=audio_blob_url,
            destination_container_url=destination_container_url,
            audio_blob_name=blob_name,
            topic=topic,
            correlation_id=correlation_id,
            enable_diarization=enable_diarization
        )


        log_with_correlation(
            logger, "info",
            f"✅ Transcription started: {transcription_id}",
            correlation_id
        )


        if is_local():
            log_with_correlation(
                logger, "info",
                "Local mode: polling for transcription completion...",
                correlation_id
            )

            wait_for_transcription_completion(
                transcription_id=transcription_id,
                correlation_id=correlation_id
            )
        else:
            # In Azure, Speech Service writes directly to transcripts container
            # Store metadata on audio blob for tracking purposes
            updated_metadata = metadata.copy()
            updated_metadata["correlation_id"] = correlation_id
            updated_metadata["topic"] = topic
            updated_metadata["transcription_id"] = transcription_id
            blob_client.set_blob_metadata(metadata=updated_metadata)
            
            log_with_correlation(
                logger, "info",
                f"Transcription {transcription_id} started. Speech Service will write results to transcripts container.",
                correlation_id
            )


    except Exception as e:
        log_with_correlation(logger, "error",
            f"❌ Error starting transcription: {str(e)}",
            correlation_id,
            exc_info=True)
        raise


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    """
    Simple health check endpoint for monitoring.
    """
    return func.HttpResponse(
        '{"status": "healthy", "service": "video-summarization"}',
        status_code=200,
        mimetype="application/json"
    )


@app.blob_trigger(arg_name="transcriptBlob",
                  path="transcripts/{name}",
                  connection="STORAGE_CONNECTION_STRING")
def transcript_blob_trigger(transcriptBlob: func.InputStream, context: func.Context):
    """
    Triggered when a transcript is uploaded to the transcripts container.
    Handles two types of files:
    1. JSON files from Speech Service (when using destinationContainerUrl)
    2. Plain text files from local dev polling
    
    Creates or updates an AI agent in Foundry with the transcript as knowledge.
    """
    import json
    
    # Get blob name without container prefix
    blob_name = transcriptBlob.name
    if blob_name.startswith(f"{TRANSCRIPTS_CONTAINER}/"):
        blob_name = blob_name[len(TRANSCRIPTS_CONTAINER)+1:]

    # Get blob metadata
    blob_client = blob_service_client.get_blob_client(container=TRANSCRIPTS_CONTAINER, blob=blob_name)
    blob_properties = blob_client.get_blob_properties()
    metadata = blob_properties.metadata or {}

    # Get correlation ID
    correlation_id = get_correlation_id(context, metadata)

    log_with_correlation(logger, "info", f"📄 Transcript blob trigger: {blob_name}", correlation_id)
    
    # Skip report files (Speech Service writes both transcription and report)
    if "_report.json" in blob_name.lower() or blob_name.endswith("report.json"):
        log_with_correlation(logger, "info", 
            f"Skipping report file: {blob_name}", 
            correlation_id)
        return
    
    try:
        # Read blob content
        raw_content = transcriptBlob.read().decode('utf-8')
        
        # Determine if this is JSON (from Speech Service) or plain text (from local dev)
        transcript_text = None
        audio_file_name = None
        topic = metadata.get("topic", "default")
        
        if blob_name.endswith('.json'):
            # JSON from Speech Service - parse it
            log_with_correlation(logger, "info", 
                "Processing JSON transcription from Speech Service", 
                correlation_id)
            
            try:
                transcription_data = json.loads(raw_content)
                
                # Extract transcript text from combinedRecognizedPhrases
                combined_phrases = transcription_data.get("combinedRecognizedPhrases", [])
                if combined_phrases:
                    transcript_text = combined_phrases[0].get("display", "")
                
                # Extract source audio filename from the source URL
                source_url = transcription_data.get("source", "")
                if source_url:
                    # Parse the audio filename from the URL
                    # Format: https://storage.blob.core.windows.net/audio/filename.mp3?sas...
                    if f"/{AUDIO_CONTAINER}/" in source_url:
                        audio_file_name = source_url.split(f"/{AUDIO_CONTAINER}/")[1].split("?")[0]
                    
                if not transcript_text:
                    log_with_correlation(logger, "warning", 
                        f"No transcript text found in JSON: {blob_name}", 
                        correlation_id)
                    return
                    
                log_with_correlation(logger, "info", 
                    f"Extracted transcript from JSON. Source audio: {audio_file_name or 'unknown'}", 
                    correlation_id)
                
                # Look up topic from audio blob metadata if we found the audio file
                if audio_file_name:
                    try:
                        audio_blob_client = blob_service_client.get_blob_client(
                            container=AUDIO_CONTAINER, 
                            blob=audio_file_name
                        )
                        audio_metadata = audio_blob_client.get_blob_properties().metadata or {}
                        topic = audio_metadata.get("topic", topic)
                        log_with_correlation(logger, "info", 
                            f"Retrieved topic '{topic}' from audio blob metadata", 
                            correlation_id)
                    except Exception as e:
                        log_with_correlation(logger, "warning", 
                            f"Could not retrieve audio metadata: {e}", 
                            correlation_id)
                
                # Save as plain text file with the audio filename for easy mapping
                if audio_file_name:
                    txt_filename = audio_file_name.rsplit(".", 1)[0] + ".txt"
                    txt_blob_client = blob_service_client.get_blob_client(
                        container=TRANSCRIPTS_CONTAINER,
                        blob=txt_filename
                    )
                    txt_blob_client.upload_blob(
                        transcript_text,
                        overwrite=True,
                        metadata={
                            "topic": topic,
                            "source_audio": audio_file_name,
                            "source_json": blob_name,
                            "correlation_id": correlation_id
                        }
                    )
                    log_with_correlation(logger, "info", 
                        f"Saved transcript as: {txt_filename}", 
                        correlation_id)
                    
            except json.JSONDecodeError as e:
                log_with_correlation(logger, "error", 
                    f"Failed to parse JSON: {e}", 
                    correlation_id)
                return
        else:
            # Plain text file (from local dev or already processed)
            transcript_text = raw_content
            audio_file_name = metadata.get("source_audio", blob_name.rsplit(".", 1)[0])
            
        if not transcript_text:
            log_with_correlation(logger, "warning", 
                "No transcript text to process", 
                correlation_id)
            return

        log_with_correlation(logger, "info", 
            f"Creating/updating agent for topic: {topic}", 
            correlation_id)

        # Initialize AI Projects client with managed identity
        credential = DefaultAzureCredential()
        project_client = AIProjectClient(
            endpoint=AI_FOUNDRY_ENDPOINT,
            credential=credential
        )

        # Save transcript text to temp file for upload to AI Foundry
        import tempfile
        from azure.ai.agents.models import FilePurpose, FileSearchTool

        # Use context manager to ensure proper cleanup
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp_file:
            tmp_file.write(transcript_text)
            temp_file_path = tmp_file.name

        try:
            # Upload file to AI Foundry
            log_with_correlation(logger, "info", "Uploading transcript to AI Foundry", correlation_id)
            file = project_client.agents.files.upload_and_poll(
                file_path=temp_file_path,
                purpose=FilePurpose.AGENTS
            )
            log_with_correlation(logger, "info", f"File uploaded: {file.id}", correlation_id)

            # Create vector store with the uploaded file
            log_with_correlation(logger, "info", "Creating vector store", correlation_id)
            vector_store = project_client.agents.vector_stores.create_and_poll(
                file_ids=[file.id],
                name=f"transcripts-{topic}"
            )
            log_with_correlation(logger, "info", f"Vector store created: {vector_store.id}", correlation_id)

            # Create file search tool
            file_search = FileSearchTool(vector_store_ids=[vector_store.id])

            # Check if agent exists for this topic
            agent_name = f"transcript-agent-{topic}"
            agent = None

            # Try to find existing agent by listing all agents
            log_with_correlation(logger, "info", f"Searching for existing agent: {agent_name}", correlation_id)
            try:
                # Try list_agents() method (SDK v1.x pattern)
                agents_list = list(project_client.agents.list_agents())
                for existing_agent in agents_list:
                    if hasattr(existing_agent, 'name') and existing_agent.name == agent_name:
                        agent = existing_agent
                        log_with_correlation(logger, "info", f"Found existing agent: {agent.id}", correlation_id)

                        # Update existing agent with new vector store
                        project_client.agents.update_agent(
                            agent_id=agent.id,
                            tools=file_search.definitions,
                            tool_resources=file_search.resources
                        )
                        log_with_correlation(logger, "info",
                            f"✅ Updated agent {agent.id} with new transcript",
                            correlation_id)
                        break
            except AttributeError:
                # list_agents() not available, will create new agent
                log_with_correlation(logger, "info", 
                    "Agent listing not available in this SDK version, creating new agent",
                    correlation_id)

            # Create new agent if doesn't exist
            if not agent:
                log_with_correlation(logger, "info", f"Creating new agent: {agent_name}", correlation_id)
                agent = project_client.agents.create_agent(
                    model="gpt-5",
                    name=agent_name,
                    instructions=(
                        "You are a helpful assistant that answers questions about transcribed audio content. "
                        "Use the provided transcript files to answer user questions accurately and cite "
                        "specific parts of the transcript when relevant."
                    ),
                    tools=file_search.definitions,
                    tool_resources=file_search.resources
                )
                log_with_correlation(logger, "info", f"✅ Created new agent: {agent.id}", correlation_id)

        finally:
            # Clean up temp file - ensure it's deleted even if errors occur
            try:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            except Exception as cleanup_error:
                log_with_correlation(logger, "warning",
                    f"Failed to cleanup temp file {temp_file_path}: {cleanup_error}",
                    correlation_id)

        log_with_correlation(logger, "info",
            f"✅ Agent workflow complete for topic '{topic}'",
            correlation_id)

    except Exception as e:
        log_with_correlation(logger, "error",
            f"❌ Error processing transcript: {str(e)}",
            correlation_id,
            exc_info=True)
        raise
