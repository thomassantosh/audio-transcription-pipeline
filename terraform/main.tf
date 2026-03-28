terraform {
  required_version = ">= 1.8, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.56.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.1"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

variable "subscription_id" {
  description = "Azure subscription ID (derived from Azure CLI context)"
  type        = string
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

provider "azapi" {
  subscription_id = var.subscription_id
}

# Generate a random string for unique naming
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# Access the client configuration of the AzureRM provider.
data "azurerm_client_config" "current" {}

# Create a resource group.
resource "azurerm_resource_group" "example" {
  name     = "rg-transcription-${random_string.suffix.result}"
  location = "WestUS3"

  tags = {
    VideoSummarization = "true"
  }
}

# Create Storage Account
resource "azurerm_storage_account" "example" {
  name                          = "transcription${random_string.suffix.result}sa"
  resource_group_name           = azurerm_resource_group.example.name
  location                      = azurerm_resource_group.example.location
  account_tier                  = "Standard"
  account_replication_type      = "LRS"
  account_kind                  = "StorageV2"
  # Required for Speech Service destinationContainerUrl feature
  # "The Storage account resource must allow all external traffic"
  public_network_access_enabled = true

  tags = {
    VideoSummarization = "true"
    SecurityControl    = "Ignore"
  }
}

# Create Audio Container for audio file uploads
resource "azurerm_storage_container" "audio" {
  name                  = "audio"
  storage_account_id    = azurerm_storage_account.example.id
  container_access_type = "private"
}

# Create Transcripts Container for transcription results
resource "azurerm_storage_container" "transcripts" {
  name                  = "transcripts"
  storage_account_id    = azurerm_storage_account.example.id
  container_access_type = "private"
}

# Create Azure Speech Service (Cognitive Services)
resource "azurerm_cognitive_account" "speech" {
  name                = "transcription${random_string.suffix.result}speech"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  kind                = "SpeechServices"
  sku_name            = "S0"

  tags = {
    VideoSummarization = "true"
    SecurityControl    = "Ignore"
  }
}

# Create Azure AI Foundry Hub (AIServices with project management)
resource "azurerm_cognitive_account" "ai_foundry" {
  name                          = "transcription${random_string.suffix.result}aiservices"
  custom_subdomain_name         = "transcription${random_string.suffix.result}aiservices"
  location                      = azurerm_resource_group.example.location
  resource_group_name           = azurerm_resource_group.example.name
  kind                          = "AIServices"
  sku_name                      = "S0"
  public_network_access_enabled = true
  project_management_enabled    = true

  identity {
    type = "SystemAssigned"
  }

  tags = {
    VideoSummarization = "true"
    SecurityControl    = "Ignore"
  }
}

# Deploy GPT-5 model to AI Foundry
resource "azurerm_cognitive_deployment" "gpt5" {
  name                 = "gpt-5"
  cognitive_account_id = azurerm_cognitive_account.ai_foundry.id

  model {
    format  = "OpenAI"
    name    = "gpt-5"
    version = "2025-08-07"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 100
  }
}

# Create AI Foundry Project using AzAPI
resource "azapi_resource" "ai_foundry_project" {
  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name                      = "project${random_string.suffix.result}"
  parent_id                 = azurerm_cognitive_account.ai_foundry.id
  location                  = azurerm_resource_group.example.location
  schema_validation_enabled = false

  body = {
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }
    properties = {
      displayName = "Transcription Project"
      description = "AI Foundry project for audio transcription and AI agents"
    }
  }

  depends_on = [
    azurerm_cognitive_account.ai_foundry
  ]
}

# Create Log Analytics Workspace for Application Insights
resource "azurerm_log_analytics_workspace" "function_app" {
  name                = "transcription${random_string.suffix.result}logs"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = {
    VideoSummarization = "true"
  }
}

# Create Application Insights for Function App monitoring
resource "azurerm_application_insights" "function_app" {
  name                = "transcription${random_string.suffix.result}ai"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  workspace_id        = azurerm_log_analytics_workspace.function_app.id
  application_type    = "web"

  tags = {
    VideoSummarization = "true"
  }
}

# Create App Service Plan for Azure Functions (Premium Plan)
resource "azurerm_service_plan" "function_app" {
  name                = "transcription${random_string.suffix.result}plan"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  os_type             = "Linux"
  sku_name            = "EP1"  # Elastic Premium 1 (EP1)

  tags = {
    VideoSummarization = "true"
  }
}

# Create Azure Function App
resource "azurerm_linux_function_app" "transcription" {
  name                             = "transcription${random_string.suffix.result}func"
  location                         = azurerm_resource_group.example.location
  resource_group_name              = azurerm_resource_group.example.name
  service_plan_id                  = azurerm_service_plan.function_app.id
  storage_account_name             = azurerm_storage_account.example.name
  storage_account_access_key       = azurerm_storage_account.example.primary_access_key
  functions_extension_version      = "~4"

  site_config {
    elastic_instance_minimum = 1
    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME"              = "python"
    "AzureWebJobsFeatureFlags"              = "EnableWorkerIndexing"
    "AzureWebJobsStorage"                   = azurerm_storage_account.example.primary_connection_string
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.function_app.connection_string
    "SPEECH_KEY"                            = azurerm_cognitive_account.speech.primary_access_key
    "SPEECH_REGION"                         = azurerm_resource_group.example.location
    "AI_FOUNDRY_ENDPOINT"                   = "${azurerm_cognitive_account.ai_foundry.endpoint}api/projects/${azapi_resource.ai_foundry_project.name}"
    "STORAGE_CONNECTION_STRING"             = azurerm_storage_account.example.primary_connection_string
    "AUDIO_CONTAINER"                       = azurerm_storage_container.audio.name
    "TRANSCRIPTS_CONTAINER"                 = azurerm_storage_container.transcripts.name
  }

  identity {
    type = "SystemAssigned"
  }

  tags = {
    VideoSummarization = "true"
  }
}

# Grant Function App managed identity permission to use AI Foundry
resource "azurerm_role_assignment" "function_app_cognitive_services_user" {
  scope                = azurerm_cognitive_account.ai_foundry.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_linux_function_app.transcription.identity[0].principal_id
}

# Grant Function App managed identity permission to write files/assets to AI Foundry
resource "azurerm_role_assignment" "function_app_cognitive_services_contributor" {
  scope                = azurerm_cognitive_account.ai_foundry.id
  role_definition_name = "Cognitive Services Contributor"
  principal_id         = azurerm_linux_function_app.transcription.identity[0].principal_id
}

# Generate .env file for local development
resource "local_file" "env_file" {
  filename = "${path.module}/../.env"
  content  = replace(<<-EOT
    # Generated by Terraform - Audio Transcription Pipeline Configuration

    # Azure Resource Group
    RESOURCE_GROUP=${azurerm_resource_group.example.name}

    # Storage Account Configuration
    STORAGE_ACCOUNT_NAME=${azurerm_storage_account.example.name}
    STORAGE_ACCOUNT_KEY=${azurerm_storage_account.example.primary_access_key}
    STORAGE_CONN_STRING=${azurerm_storage_account.example.primary_connection_string}

    # Azure Speech Service Configuration
    SPEECH_KEY=${azurerm_cognitive_account.speech.primary_access_key}
    SPEECH_REGION=${azurerm_cognitive_account.speech.location}
    SPEECH_ENDPOINT=${azurerm_cognitive_account.speech.endpoint}

    # Azure AI Foundry Configuration
    AI_SERVICES_ENDPOINT=${azurerm_cognitive_account.ai_foundry.endpoint}
    AI_FOUNDRY_ENDPOINT=https://${azurerm_cognitive_account.ai_foundry.name}.services.ai.azure.com/api/projects/${azapi_resource.ai_foundry_project.name}

    # Azure Function App Configuration
    FUNCTION_APP_NAME=${azurerm_linux_function_app.transcription.name}
    FUNCTION_APP_URL=${azurerm_linux_function_app.transcription.default_hostname}

    # Audio Pipeline Storage Containers
    AUDIO_CONTAINER=${azurerm_storage_container.audio.name}
    TRANSCRIPTS_CONTAINER=${azurerm_storage_container.transcripts.name}
    STORAGE_CONNECTION_STRING=${azurerm_storage_account.example.primary_connection_string}

    # Application Insights Configuration
    APPINSIGHTS_INSTRUMENTATION_KEY=${azurerm_application_insights.function_app.instrumentation_key}
    APPINSIGHTS_CONNECTION_STRING=${azurerm_application_insights.function_app.connection_string}
  EOT
  , "\r", "")
}

# Resource Group Name
output "resource_group" {
  value       = azurerm_resource_group.example.name
  description = "The name of the resource group"
}

# Storage Account Name
output "storage_account" {
  value       = azurerm_storage_account.example.name
  description = "The name of the storage account"
}

# Storage Account Connection String
output "storage_conn_string" {
  value       = azurerm_storage_account.example.primary_connection_string
  description = "The primary connection string for the storage account"
  sensitive   = true
}

# Storage Account Key
output "storage_account_key" {
  value       = azurerm_storage_account.example.primary_access_key
  description = "The primary access key for the storage account"
  sensitive   = true
}

# Speech Service Key
output "speech_key" {
  value       = azurerm_cognitive_account.speech.primary_access_key
  description = "The primary access key for the Speech Service"
  sensitive   = true
}

# Speech Service Region
output "speech_region" {
  value       = azurerm_cognitive_account.speech.location
  description = "The region of the Speech Service"
}

# Speech Service Endpoint
output "speech_endpoint" {
  value       = azurerm_cognitive_account.speech.endpoint
  description = "The endpoint for the Speech Service"
}

# AI Services Endpoint (for Speech, Vision, etc. - uses cognitiveservices.azure.com)
output "ai_services_endpoint" {
  value       = azurerm_cognitive_account.ai_foundry.endpoint
  description = "The Cognitive Services endpoint for AI services (Speech, etc.)"
}

# AI Foundry Project Endpoint (for Agents - uses services.ai.azure.com)
output "ai_foundry_endpoint" {
  value       = "https://${azurerm_cognitive_account.ai_foundry.name}.services.ai.azure.com/api/projects/${azapi_resource.ai_foundry_project.name}"
  description = "The endpoint for Azure AI Foundry Project (Agents SDK)"
}

# AI Foundry Project ID
output "ai_foundry_project_id" {
  value       = azapi_resource.ai_foundry_project.id
  description = "The resource ID for Azure AI Foundry Project"
}

# Function App Name
output "function_app_name" {
  value       = azurerm_linux_function_app.transcription.name
  description = "The name of the Function App"
}

# Function App URL
output "function_app_url" {
  value       = azurerm_linux_function_app.transcription.default_hostname
  description = "The default hostname of the Function App"
}

# Audio Container Name
output "audio_container_name" {
  value       = azurerm_storage_container.audio.name
  description = "The name of the audio storage container"
}

# Transcripts Container Name
output "transcripts_container_name" {
  value       = azurerm_storage_container.transcripts.name
  description = "The name of the transcripts storage container"
}

# Application Insights Instrumentation Key
output "appinsights_instrumentation_key" {
  value       = azurerm_application_insights.function_app.instrumentation_key
  description = "The instrumentation key for Application Insights"
  sensitive   = true
}

# Application Insights Connection String
output "appinsights_connection_string" {
  value       = azurerm_application_insights.function_app.connection_string
  description = "The connection string for Application Insights"
  sensitive   = true
}
