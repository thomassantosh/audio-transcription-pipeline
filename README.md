# Audio Transcription Pipeline
This project provides an automated audio transcription pipeline using Azure services. Upload audio files to Azure Blob Storage,
automatically transcribe them using Azure Speech Service with optional speaker diarization, and load transcripts into Azure AI
Foundry agents for interactive Q&A. Audio files are retrieved using youtube-dl, in an m4a format.

## How It Works

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Audio File  │────▶│ Blob Trigger     │────▶│ Speech Service  │
│ (+ metadata)│     │ (Function)       │     │ (Transcription) │
└─────────────┘     └──────────────────┘     └─────────────────┘
                                                       │
                          destinationContainerUrl      │
                    (Speech writes JSON directly)      │
                                                       ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ AI Agent    │◀────│ Blob Trigger     │◀────│ Transcript JSON │
│ (Q&A ready) │     │ (Function)       │     │ + .txt file     │
└─────────────┘     └──────────────────┘     └─────────────────┘
```

### Architecture Notes
- **Local Development**: Uses polling to wait for transcription completion
- **Azure Deployment**: Uses `destinationContainerUrl` - Speech Service writes JSON directly to the transcripts container
- The blob trigger parses the JSON, extracts the transcript text, and saves a `.txt` file with the original audio filename
- The `.txt` file is then uploaded to Azure AI Foundry for agent-based Q&A

## Notes
- Azure Speech Service supports: WAV MP3 OGG/OPUS FLAC AMR WEBM (NOT m4a - use `make convert-audio`)
- Transcripts are saved as `.txt` files with the same name as the source audio file.
- **diarization**: `true` enables speaker separation, `false` for single speaker
- **topic**: Groups transcripts under the same AI agent (e.g., "project-planning")

## Quick Start

Run `make help` to see all available commands.
