- Goal of this repo is to be able to get a video (most likely a Youtube video), transcribe it and then have GPT processing help
  discern the key elements of the video. This is helpful in 1-1 conversations, or in conversations between two presenters.
  
- For GPT processing:
	- Discern facts
	- Discern specific questions raised.

- Workflow:
	- Need a storage container that then triggers some compute (container app) to process. Once successful, GPT processing kicks in.
	- Elements: container apps, GPT model, storage container, transcription model (understand constraints).
	- Can use batch processing for this, but suspect you may have a large number of adhoc requests.

- Pending:
	- What about image processing?
	- How do you discern between a conversation vs. one person speaking?
