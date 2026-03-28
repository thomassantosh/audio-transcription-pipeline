help: ## Show this help message (grouped by sections)
	@echo ""
	@echo "\033[1;36m╔══════════════════════════════════════════════════════════════════════╗\033[0m"
	@echo "\033[1;36m║                        Video summarization                           ║\033[0m"
	@echo "\033[1;36m╚══════════════════════════════════════════════════════════════════════╝\033[0m"
	@echo ""
	@echo "  \033[36m●\033[0m \033[36mcore\033[0m = Primary workflows    \033[33m○\033[0m \033[33mutil\033[0m = Utilities"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} \
		/^##@/ {printf "\n\033[1;35m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z0-9_.-]+:.*?## \[core\]/ {gsub(/\[core\] */, "", $$2); printf "  \033[36m●\033[0m \033[36m%-38s\033[0m %s\n", $$1, $$2; next} \
		/^[a-zA-Z0-9_.-]+:.*?## \[util\]/ {gsub(/\[util\] */, "", $$2); printf "  \033[33m○\033[0m \033[33m%-38s\033[0m %s\n", $$1, $$2; next} \
		/^[a-zA-Z0-9_.-]+:.*?## / {printf "    %-40s %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)
	@echo ""


##@ Terraform Setup
init: ## [util] Initialize Terraform with providers
	cd terraform && terraform init

validate: init ## [util] Validate Terraform configuration
	cd terraform && terraform validate

plan: ## [util] Create Terraform execution plan
	cd terraform && terraform plan -var="subscription_id=$$(az account show --query id -o tsv)" -out=tfplan

apply: ## [util] Apply Terraform changes
	cd terraform && terraform apply tfplan

deploy: ## [core] Full deployment: clean, init, plan, and apply
	rm -rf .env
	make clean
	make init
	make plan
	make apply

clean-containers: ## [util] Delete all blobs in audio and transcripts containers
	@echo "Cleaning audio and transcripts containers..."
	@STORAGE_CONN_STRING=$$(grep STORAGE_CONNECTION_STRING .env | cut -d'=' -f2-); \
	if [ -z "$$STORAGE_CONN_STRING" ]; then \
		echo "Error: .env file not found. Run 'make get-output' first"; \
		exit 1; \
	fi; \
	echo "Deleting blobs from audio container..."; \
	az storage blob delete-batch --delete-snapshots include --source audio --connection-string "$$STORAGE_CONN_STRING" 2>/dev/null || echo "Audio container is empty or already clean"; \
	echo "Deleting blobs from transcripts container..."; \
	az storage blob delete-batch --delete-snapshots include --source transcripts --connection-string "$$STORAGE_CONN_STRING" 2>/dev/null || echo "Transcripts container is empty or already clean"; \
	echo "✓ Containers cleaned successfully"

delete: clean-containers ## [core] Delete all Azure resource groups with VideoSummarization tag
	@echo "Finding resource groups with VideoSummarization=true tag..."
	@az group list --tag VideoSummarization=true --query "[].name" -o tsv | while read rg; do \
		if [ -n "$$rg" ]; then \
			echo "Deleting resource group: $$rg"; \
			(az group delete --name "$$rg" --yes --no-wait 2>&1 | grep -v "Bad Request" || true) && \
			echo "Deletion initiated for: $$rg"; \
		fi; \
	done
	@echo "All deletions initiated. They will complete in the background."

clean: ## [util] Clean Terraform state and cache files
	rm -rf terraform/.terraform
	rm -f terraform/.terraform.lock.hcl
	rm -f terraform/terraform.tfstate
	rm -f terraform/terraform.tfstate.backup
	rm -f terraform/tfplan

##@ Function app operations
uv-sync: ## [util] Sync Python dependencies using uv
	uv sync --locked

update-local-settings: ## [util] Update local.settings.json with values from .env
	@echo "Updating local.settings.json with credentials from .env..."
	@cd function_app && \
	jq '.Values.AzureWebJobsStorage = "'$$(grep STORAGE_CONNECTION_STRING ../\.env | cut -d'=' -f2-)'"' local.settings.json | \
	jq '.Values.STORAGE_CONNECTION_STRING = "'$$(grep STORAGE_CONNECTION_STRING ../\.env | cut -d'=' -f2-)'"' | \
	jq '.Values.SPEECH_KEY = "'$$(grep SPEECH_KEY ../\.env | cut -d'=' -f2-)'"' | \
	jq '.Values.SPEECH_REGION = "'$$(grep SPEECH_REGION ../\.env | cut -d'=' -f2-)'"' | \
	jq '.Values.AI_FOUNDRY_ENDPOINT = "'$$(grep AI_FOUNDRY_ENDPOINT ../\.env | cut -d'=' -f2-)'"' | \
	jq '.Values.PYTHONPATH = ".python_packages"' > local.settings.json.tmp && \
	mv local.settings.json.tmp local.settings.json
	@echo "✓ local.settings.json updated successfully"

function-local: update-local-settings clean-containers ## [util] Run Azure Functions locally
	@echo "Installing dependencies for local Functions runtime..."
	@rm -rf function_app/.python_packages
	@cd function_app && python3.11 -m pip install -r requirements.txt -t .python_packages --quiet
	@echo "Starting Azure Functions locally with Python 3.11..."
	@which func > /dev/null || (echo "Error: Azure Functions Core Tools not installed. Install with: npm install -g azure-functions-core-tools@4" && exit 1)
	@mkdir -p function_app/.bin
	@ln -sf /opt/homebrew/bin/python3.11 function_app/.bin/python3
	@cd function_app && PATH="$$PWD/.bin:$$PATH" func start
	@rm -f function_app/.bin/python3

# Fetch transcription from Azure Speech Service and save locally
# Checks status first, exits if still running, downloads when complete
fetch-transcription: ## [util] Download transcription locally (Usage: make fetch-transcription ID=<id> NAME=output.txt)
	@if [ -z "$(ID)" ] || [ -z "$(NAME)" ]; then \
		echo "Error: ID and NAME parameters required."; \
		echo "Usage: make fetch-transcription ID=<transcription-id> NAME=output.txt"; \
		echo "Find the transcription ID with: make show-audio-metadata NAME=<audio-file>"; \
		exit 1; \
	fi
	@SPEECH_KEY=$$(grep SPEECH_KEY .env | cut -d'=' -f2); \
	SPEECH_REGION=$$(grep SPEECH_REGION .env | cut -d'=' -f2); \
	echo "Checking transcription status..."; \
	STATUS=$$(curl -s -X GET "https://$${SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2/transcriptions/$(ID)" \
		-H "Ocp-Apim-Subscription-Key: $${SPEECH_KEY}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','Unknown'))"); \
	echo "Status: $$STATUS"; \
	if [ "$$STATUS" = "Running" ] || [ "$$STATUS" = "NotStarted" ]; then \
		echo "⏳ Transcription still in progress. Try again later."; \
		exit 0; \
	elif [ "$$STATUS" = "Failed" ]; then \
		echo "❌ Transcription failed. Check Azure portal for details."; \
		exit 1; \
	elif [ "$$STATUS" != "Succeeded" ]; then \
		echo "❌ Unknown status: $$STATUS"; \
		exit 1; \
	fi; \
	echo "Fetching transcription files..."; \
	CONTENT_URL=$$(curl -s -X GET "https://$${SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2/transcriptions/$(ID)/files" \
		-H "Ocp-Apim-Subscription-Key: $${SPEECH_KEY}" | \
		python3 -c "import sys,json; files=json.load(sys.stdin)['values']; print(next(f['links']['contentUrl'] for f in files if f['kind']=='Transcription'))"); \
	echo "Downloading transcript..."; \
	curl -s "$$CONTENT_URL" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['combinedRecognizedPhrases'][0]['display'])" > $(NAME); \
	echo "✓ Transcription saved to $(NAME)"

# Once the application is live, use the Log Stream to see continuous logs (Hit 'Clear' to checkpoint)
function-deploy: ## [core] Deploy function app to Azure
	@which func > /dev/null || (echo "Error: Azure Functions Core Tools not installed. Install with: npm install -g azure-functions-core-tools@4" && exit 1)
	@if [ -z "$$(grep FUNCTION_APP_NAME .env 2>/dev/null)" ]; then \
		echo "Error: .env file not found. Run 'make get-output' first"; \
		exit 1; \
	fi
	@FUNC_APP=$$(grep FUNCTION_APP_NAME .env | cut -d'=' -f2); \
	echo "Deploying to Function App: $$FUNC_APP"; \
	cd function_app && func azure functionapp publish $$FUNC_APP --python

# Test that the health endpoint is accessible after deployment
test-health: ## [util] Test health endpoint is accessible (run after function-deploy)
	@if [ -z "$$(grep FUNCTION_APP_NAME .env 2>/dev/null)" ]; then \
		echo "Error: .env file not found. Run 'make get-output' first"; \
		exit 1; \
	fi
	@FUNC_APP=$$(grep FUNCTION_APP_NAME .env | cut -d'=' -f2); \
	echo "Testing health endpoint at https://$$FUNC_APP.azurewebsites.net/api/health"; \
	RESPONSE=$$(curl -s -w "\\n%{http_code}" -X GET "https://$$FUNC_APP.azurewebsites.net/api/health"); \
	HTTP_CODE=$$(echo "$$RESPONSE" | tail -n1); \
	BODY=$$(echo "$$RESPONSE" | sed '$$d'); \
	echo "Response: $$BODY"; \
	echo "HTTP Status: $$HTTP_CODE"; \
	if [ "$$HTTP_CODE" = "200" ]; then \
		echo "✓ Health endpoint is accessible"; \
	else \
		echo "⚠ Health check failed"; \
		exit 1; \
	fi

# Restart the deployed function app
function-restart: ## [util] Restart the deployed function app
	@FUNC_APP=$$(grep FUNCTION_APP_NAME .env | cut -d'=' -f2); \
	RG=$$(grep RESOURCE_GROUP .env | cut -d'=' -f2); \
	echo "Restarting function app: $$FUNC_APP"; \
	az functionapp restart --name "$$FUNC_APP" --resource-group "$$RG"; \
	echo "✓ Function app restarted"

# Stream function app logs
function-logs: ## [util] Stream function app deployment logs
	@FUNC_APP=$$(grep FUNCTION_APP_NAME .env | cut -d'=' -f2); \
	RG=$$(grep RESOURCE_GROUP .env | cut -d'=' -f2); \
	echo "Streaming logs for: $$FUNC_APP"; \
	az functionapp log deployment show --name "$$FUNC_APP" --resource-group "$$RG"

# List blobs in audio container
list-audio: ## [util] List audio files in blob storage
	@CONN_STRING=$$(grep STORAGE_CONNECTION_STRING .env | cut -d'=' -f2-); \
	az storage blob list --container-name audio --connection-string "$$CONN_STRING" --output table

# Show metadata for a specific audio blob (includes transcription_id)
show-audio-metadata: ## [util] Show audio blob metadata (Usage: make show-audio-metadata NAME=file.mp3)
	@if [ -z "$(NAME)" ]; then \
		echo "Error: NAME parameter required."; \
		echo "Usage: make show-audio-metadata NAME=part1.mp3"; \
		exit 1; \
	fi
	@CONN_STRING=$$(grep STORAGE_CONNECTION_STRING .env | cut -d'=' -f2-); \
	az storage blob metadata show --container-name audio --name "$(NAME)" --connection-string "$$CONN_STRING"

# List blobs in transcripts container
list-transcripts: ## [util] List transcript files in blob storage
	@CONN_STRING=$$(grep STORAGE_CONNECTION_STRING .env | cut -d'=' -f2-); \
	az storage blob list --container-name transcripts --connection-string "$$CONN_STRING" --output table

# Show detailed transcription info from Speech Service API
show-transcription: ## [util] Show transcription details from Speech API (Usage: make show-transcription ID=<transcription-id>)
	@if [ -z "$(ID)" ]; then \
		echo "Error: ID parameter required."; \
		echo "Usage: make show-transcription ID=<transcription-id>"; \
		echo "Find the transcription ID with: make show-audio-metadata NAME=<audio-file>"; \
		exit 1; \
	fi
	@SPEECH_KEY=$$(grep SPEECH_KEY .env | cut -d'=' -f2); \
	SPEECH_REGION=$$(grep SPEECH_REGION .env | cut -d'=' -f2); \
	curl -s -X GET "https://$${SPEECH_REGION}.api.cognitive.microsoft.com/speechtotext/v3.2/transcriptions/$(ID)" \
		-H "Ocp-Apim-Subscription-Key: $${SPEECH_KEY}" | python3 -m json.tool


##@ Upload Audio & Query Agent
# Convert m4a to mp3 (Azure Speech Service doesn't support m4a)
convert-audio: ## [util] Convert audio to MP3 (Usage: make convert-audio INPUT=file.m4a OUTPUT=file.mp3)
	@if [ -z "$(INPUT)" ] || [ -z "$(OUTPUT)" ]; then \
		echo "Error: INPUT and OUTPUT parameters required."; \
		echo "Usage: make convert-audio INPUT=file.m4a OUTPUT=file.mp3"; \
		exit 1; \
	fi
	@which ffmpeg > /dev/null || (echo "Error: ffmpeg not installed. Install with: brew install ffmpeg" && exit 1)
	ffmpeg -i $(INPUT) -vn -acodec libmp3lame -q:a 2 $(OUTPUT)
	@echo "✓ Converted $(INPUT) to $(OUTPUT)"

upload-audio: uv-sync ## [core] Upload audio file (Usage: make upload-audio FILE=audio.mp3 [DIARIZATION=true] [TOPIC=mytopic])
	@if [ -z "$(FILE)" ]; then \
		echo "Error: FILE parameter required. Usage: make upload-audio FILE=audio.mp3"; \
		exit 1; \
	fi
	@DIARIZATION_FLAG=""; \
	if [ "$(DIARIZATION)" = "true" ]; then \
		DIARIZATION_FLAG="--diarization"; \
	fi; \
	TOPIC_FLAG=""; \
	if [ -n "$(TOPIC)" ]; then \
		TOPIC_FLAG="--topic $(TOPIC)"; \
	fi; \
	uv run scripts/upload_audio.py $(FILE) $$DIARIZATION_FLAG $$TOPIC_FLAG

query-agent: uv-sync ## [core] Query AI agent about transcripts (Usage: make query-agent TOPIC=mytopic QUESTION="What was discussed?")
	@if [ -z "$(TOPIC)" ] || [ -z "$(QUESTION)" ]; then \
		echo "Error: TOPIC and QUESTION parameters required."; \
		echo "Usage: make query-agent TOPIC=mytopic QUESTION=\"What was discussed?\""; \
		exit 1; \
	fi
	@uv run scripts/query_agent.py $(TOPIC) "$(QUESTION)"

# Cleanup all agents and threads from Azure AI Foundry
cleanup-agents: uv-sync ## [util] Delete all agents and threads from Azure AI Foundry
	@uv run scripts/cleanup_agents.py
