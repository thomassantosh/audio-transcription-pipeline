# Audio Transcription Pipeline
This project provides an automated audio transcription pipeline using Azure services. Audio files are retrieved using youtube-dl, in an m4a format.

## Scenarios
- Upload audio files to Azure Blob Storage, automatically transcribe them using Azure Speech Service with optional speaker diarization, and load transcripts into Azure AI Foundry agents for interactive Q&A.
- Get transcripts and then use those to populate the Researcher Agent to get a comprehensive overview.

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
- Alongside the plain `.txt`, a `.timestamps.txt` file is saved with per-phrase timestamps (`[HH:MM:SS]`) and speaker labels when diarization is enabled
- The `.txt` file is then uploaded to Azure AI Foundry for agent-based Q&A (the derived `.timestamps.txt` artifact is skipped)
- For individual audio/videos, you can always use `youtube-transcript-api`

## Notes
- Azure Speech Service supports: WAV MP3 OGG/OPUS FLAC AMR WEBM (NOT m4a - use `make convert-audio`)
- Transcripts are saved as `.txt` files with the same name as the source audio file.
- A companion `.timestamps.txt` artifact is also produced with `[HH:MM:SS]` timestamps per phrase (plus speaker labels when diarized). Download it straight from the transcripts container with `make download-transcript NAME=<file>.timestamps.txt`. (You can also re-derive it from the Speech API with `make fetch-timestamps ID=<id> NAME=output.txt`, but that depends on the Speech Service content URL still being retrievable; the container blob is the reliable source.)
- **diarization**: `true` enables speaker separation, `false` for single speaker
- **topic**: Groups transcripts under the same AI agent (e.g., "project-planning")
- Uploads larger than 4 MiB use 4 MiB blocks with the Azure SDK's retry policy and a 120-second client-side connection timeout to accommodate slower connections.
- `make process-audio` stops on upload failure. Its completion message confirms conversion/upload only, not completion of the asynchronous transcription.

## Quick Start

Run `make help` to see all available commands.
