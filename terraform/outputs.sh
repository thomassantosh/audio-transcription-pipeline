#!/bin/bash
# Script to extract Terraform outputs and create .env file

# Colors for output
grn=$'\e[1;32m'
end=$'\e[0m'

printf "${grn}Extracting Terraform outputs to .env file...${end}\n"

# Change to terraform directory
cd "$(dirname "$0")"

# Create .env file in the root directory
ENV_FILE="../.env"

# Extract outputs using terraform output command
printf "${grn}Reading Terraform outputs...${end}\n"

# Resource Group
RESOURCE_GROUP=$(terraform output -raw resource_group)

# Storage Account outputs
STORAGE_ACCOUNT=$(terraform output -raw storage_account)
STORAGE_CONN_STRING=$(terraform output -raw storage_conn_string)

# Speech Service outputs
SPEECH_KEY=$(terraform output -raw speech_key)
SPEECH_REGION=$(terraform output -raw speech_region)
SPEECH_ENDPOINT=$(terraform output -raw speech_endpoint)

# AI Foundry outputs
AI_FOUNDRY_ENDPOINT=$(terraform output -raw ai_foundry_endpoint)

# Function App outputs
FUNCTION_APP_NAME=$(terraform output -raw function_app_name)
FUNCTION_APP_URL=$(terraform output -raw function_app_url)

# Audio pipeline container outputs
AUDIO_CONTAINER=$(terraform output -raw audio_container_name)
TRANSCRIPTS_CONTAINER=$(terraform output -raw transcripts_container_name)

# Application Insights outputs
APPINSIGHTS_INSTRUMENTATION_KEY=$(terraform output -raw appinsights_instrumentation_key)
APPINSIGHTS_CONNECTION_STRING=$(terraform output -raw appinsights_connection_string)

# Write to .env file
printf "${grn}Writing outputs to $ENV_FILE...${end}\n"

cat > $ENV_FILE <<EOF
# Azure Resource Group
RESOURCE_GROUP=$RESOURCE_GROUP

# Storage Account Configuration
STORAGE_ACCOUNT=$STORAGE_ACCOUNT
STORAGE_CONN_STRING=$STORAGE_CONN_STRING

# Azure Speech Service Configuration
SPEECH_KEY=$SPEECH_KEY
SPEECH_REGION=$SPEECH_REGION
SPEECH_ENDPOINT=$SPEECH_ENDPOINT

# Azure AI Foundry Configuration
AI_FOUNDRY_ENDPOINT=$AI_FOUNDRY_ENDPOINT

# Azure Function App Configuration
FUNCTION_APP_NAME=$FUNCTION_APP_NAME
FUNCTION_APP_URL=$FUNCTION_APP_URL

# Audio Pipeline Storage Containers
AUDIO_CONTAINER=$AUDIO_CONTAINER
TRANSCRIPTS_CONTAINER=$TRANSCRIPTS_CONTAINER
STORAGE_CONNECTION_STRING=$STORAGE_CONN_STRING

# Application Insights Configuration
APPINSIGHTS_INSTRUMENTATION_KEY=$APPINSIGHTS_INSTRUMENTATION_KEY
APPINSIGHTS_CONNECTION_STRING=$APPINSIGHTS_CONNECTION_STRING
EOF

printf "${grn}✓ .env file created successfully at $ENV_FILE${end}\n"
printf "${grn}✓ Total variables exported: $(wc -l < $ENV_FILE | tr -d ' ')${end}\n"
