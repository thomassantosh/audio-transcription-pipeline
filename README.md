# Audio Transcription Pipeline
This project provides an automated audio transcription pipeline using Azure services. Upload audio files to Azure Blob Storage,
automatically transcribe them using Azure Speech Service with optional speaker diarization, and load transcripts into Azure AI
Foundry agents for interactive Q&A.

## How It Works

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Audio File  │────▶│ Blob Trigger     │────▶│ Speech Service  │
│ (+ metadata)│     │ (Function)       │     │ (Transcription) │
└─────────────┘     └──────────────────┘     └─────────────────┘
                                                       │
                                                       ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ AI Agent    │◀────│ Blob Trigger     │◀────│ Transcript      │
│ (Q&A ready) │     │ (Function)       │     │ (.txt file)     │
└─────────────┘     └──────────────────┘     └─────────────────┘
```

## Notes
- Azure Speech Service supports: WAV MP3 OGG/OPUS FLAC AMR WEBM
- Transcripts are saved as `.txt` files with the same name as the source audio file.
- **diarization**: `true` enables speaker separation, `false` for single speaker
- **topic**: Groups transcripts under the same AI agent (e.g., "project-planning")

## Monitoring

```bash
# Restart the function app
az functionapp restart --name $(grep FUNCTION_APP_NAME .env | cut -d'=' -f2) --resource-group $(grep RESOURCE_GROUP .env | cut -d'=' -f2)
```

```bash
# Stream function app logs
az functionapp log deployment show --name <FUNCTION_APP_NAME> --resource-group <RESOURCE_GROUP>
az functionapp log deployment show --name $(grep FUNCTION_APP_NAME .env | cut -d'=' -f2) --resource-group $(grep RESOURCE_GROUP .env | cut -d'=' -f2)
```

```bash
# List audio files
az storage blob list --account-name <STORAGE_ACCOUNT> --container-name audio

# List transcripts
az storage blob list --account-name <STORAGE_ACCOUNT> --container-name transcripts
az storage blob list --account-name $(grep STORAGE_ACCOUNT .env | cut -d'=' -f2) --container-name transcripts --connection-string "$(grep STORAGE_CONNECTION_STRING .env | cut -d'=' -f2)"
```
