##@ "Terraform Setup"
## Initialize Terraform with providers
init:
	cd terraform && terraform init

## Validate Terraform configuration
validate: init
	cd terraform && terraform validate

## Format Terraform files
fmt:
	cd terraform && terraform fmt

## Create Terraform execution plan
plan:
	cd terraform && terraform plan -out=tfplan

## Apply Terraform changes
apply:
	cd terraform && terraform apply tfplan

deploy: ## Full deployment: clean, init, plan, and apply
	make clean
	make init
	make plan
	make apply

get-output: ## Extract Terraform outputs and create .env file
	rm -rf .env
	./terraform/outputs.sh

##@ "Deploy function app to infra"
function-deploy: uv-sync ## Deploy function app to Azure
	@which func > /dev/null || (echo "Error: Azure Functions Core Tools not installed. Install with: npm install -g azure-functions-core-tools@4" && exit 1)
	@if [ -z "$$(grep FUNCTION_APP_NAME .env 2>/dev/null)" ]; then \
		echo "Error: .env file not found. Run 'make get-output' first"; \
		exit 1; \
	fi
	@FUNC_APP=$$(grep FUNCTION_APP_NAME .env | cut -d'=' -f2); \
	echo "Deploying to Function App: $$FUNC_APP"; \
	cd function_app && func azure functionapp publish $$FUNC_APP --python

##@ "Upload Audio & Query Agent"
# Example: make upload-audio FILE=meeting.mp3 DIARIZATION=true TOPIC=team-meeting
upload-audio: uv-sync ## Upload audio file (Usage: make upload-audio FILE=audio.mp3 [DIARIZATION=true] [TOPIC=mytopic])
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


##@ "Run Agent"
query-agent: uv-sync ## Query AI agent about transcripts (Usage: make query-agent TOPIC=mytopic QUESTION="What was discussed?")
	@if [ -z "$(TOPIC)" ] || [ -z "$(QUESTION)" ]; then \
		echo "Error: TOPIC and QUESTION parameters required."; \
		echo "Usage: make query-agent TOPIC=mytopic QUESTION=\"What was discussed?\""; \
		exit 1; \
	fi
	@uv run scripts/query_agent.py $(TOPIC) "$(QUESTION)"

##@ "Local function app setup & testing"
uv-sync: ## Sync Python dependencies using uv
	uv sync --locked

update-local-settings: get-output ## Update local.settings.json with values from .env
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

function-local: update-local-settings ## Run Azure Functions locally
	@echo "Installing dependencies for local Functions runtime..."
	@rm -rf function_app/.python_packages
	@cd function_app && python3.11 -m pip install -r requirements.txt -t .python_packages --quiet
	@echo "Starting Azure Functions locally with Python 3.11..."
	@which func > /dev/null || (echo "Error: Azure Functions Core Tools not installed. Install with: npm install -g azure-functions-core-tools@4" && exit 1)
	@mkdir -p function_app/.bin
	@ln -sf /opt/homebrew/bin/python3.11 function_app/.bin/python3
	@cd function_app && PATH="$$PWD/.bin:$$PATH" func start
	@rm -f function_app/.bin/python3


##@ "Terraform cleanup"
delete: ## Delete all Azure resource groups with TerraformManaged tag
	@echo "Finding resource groups with TerraformManaged=true tag..."
	@az group list --tag TerraformManaged=true --query "[].name" -o tsv | while read rg; do \
		if [ -n "$$rg" ]; then \
			echo "Deleting resource group: $$rg"; \
			(az group delete --name "$$rg" --yes --no-wait 2>&1 | grep -v "Bad Request" || true) && \
			echo "Deletion initiated for: $$rg"; \
		fi; \
	done
	@echo "All deletions initiated. They will complete in the background."

clean: ## Clean Terraform state and cache files
	rm -rf terraform/.terraform
	rm -f terraform/.terraform.lock.hcl
	rm -f terraform/terraform.tfstate
	rm -f terraform/terraform.tfstate.backup
	rm -f terraform/tfplan

##@ Help
help: ## Show this help message (grouped by sections)
	@awk 'BEGIN {FS = ":.*?## "} \
		/^##@/ {printf "\n\033[1;35m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)
