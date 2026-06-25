################################################################################
# Sondra Keys Legal — AKS Landing Zone
#
# Azure Verified Modules (AVM) references:
#   VNet    : https://registry.terraform.io/modules/Azure/avm-res-network-virtualnetwork/azurerm
#   ACR     : https://registry.terraform.io/modules/Azure/avm-res-containerregistry-registry/azurerm
#   AKS     : https://registry.terraform.io/modules/Azure/avm-res-containerservice-managedcluster/azurerm
#   AI Svcs : https://registry.terraform.io/modules/Azure/avm-res-cognitiveservices-account/azurerm
################################################################################

locals {
  app_name    = "sondra-keys"
  environment = "dev"
  location    = "eastus"

  # Naming — <type>-<app>-<env>
  resource_group_name = "rg-${local.app_name}-${local.environment}"
  vnet_name           = "vnet-${local.app_name}-${local.environment}"
  aks_name            = "aks-${local.app_name}-${local.environment}"
  # ACR names must be alphanumeric, 5-50 chars, globally unique
  acr_name         = "acrsondrakeys${local.environment}"
  ai_services_name = "cog-${local.app_name}-${local.environment}"

  tags = {
    project     = local.app_name
    environment = local.environment
    managed_by  = "terraform"
    cost_center = "learning"
  }
}

# ────────────────────────────────────────────────
# Resource Group
# ────────────────────────────────────────────────
resource "azurerm_resource_group" "main" {
  name     = local.resource_group_name
  location = local.location
  tags     = local.tags
}

# ────────────────────────────────────────────────
# Virtual Network — AVM
# Provides isolated network space for the AKS cluster.
# ────────────────────────────────────────────────
module "vnet" {
  source  = "Azure/avm-res-network-virtualnetwork/azurerm"
  version = "~> 0.7"

  name                = local.vnet_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  address_space = ["10.0.0.0/16"]

  subnets = {
    aks = {
      name             = "snet-aks"
      address_prefixes = ["10.0.1.0/24"]
    }
  }

  enable_telemetry = false
}

# ────────────────────────────────────────────────
# Azure Container Registry — AVM
# Cost-optimized: Basic tier (~$5/month).
# Admin access is disabled; AKS uses the AcrPull role instead.
# ────────────────────────────────────────────────
module "acr" {
  source  = "Azure/avm-res-containerregistry-registry/azurerm"
  version = "~> 0.4"

  name                = local.acr_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  sku           = "Basic"
  admin_enabled = false # Enforce managed identity auth only

  enable_telemetry = false
}

# ────────────────────────────────────────────────
# AKS Cluster — Native Resource (Replaces Hallucinated AVM)
# ────────────────────────────────────────────────
resource "azurerm_kubernetes_cluster" "aks" {
  name                = local.aks_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags

  sku_tier           = "Free"
  kubernetes_version = "1.30"

  default_node_pool {
    name       = "system"
    vm_size    = "Standard_B2s"
    node_count = 1

    vnet_subnet_id = module.vnet.subnets["aks"].resource_id

    enable_auto_scaling = false
    os_disk_size_gb     = 30
    os_disk_type        = "Managed"
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin = "azure"
    service_cidr   = "10.1.0.0/16"
    dns_service_ip = "10.1.0.10"
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true
}

# Grant AKS kubelet identity permission to pull images from ACR
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = module.acr.resource_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id

  depends_on = [azurerm_kubernetes_cluster.aks, module.acr]
}

# ────────────────────────────────────────────────
# Azure AI Services (Cognitive Services) — AVM
# Single multi-service account covers: Content Understanding,
# Language, Vision, and Form Recognizer APIs.
# Cost: S0 pay-per-use, ~$1–5/month for dev workloads.
# ────────────────────────────────────────────────
module "ai_services" {
  source  = "Azure/avm-res-cognitiveservices-account/azurerm"
  version = "~> 0.5"

  name      = local.ai_services_name
  parent_id = azurerm_resource_group.main.id
  location  = azurerm_resource_group.main.location
  tags      = local.tags

  kind     = "CognitiveServices"
  sku_name = "S0"

  # Allow public access for dev. In prod: set to false and use a private endpoint.
  public_network_access_enabled = true

  enable_telemetry = false
}

# ────────────────────────────────────────────────
# Outputs
# After `terraform apply`, copy these values into GitHub Variables/Secrets.
# ────────────────────────────────────────────────
output "resource_group_name" {
  description = "→ GitHub Variable: AZURE_RESOURCE_GROUP"
  value       = azurerm_resource_group.main.name
}

output "aks_cluster_name" {
  description = "→ GitHub Variable: AKS_CLUSTER_NAME"
  value       = azurerm_kubernetes_cluster.aks.name
}

output "acr_name" {
  description = "→ GitHub Variable: ACR_NAME"
  value       = module.acr.resource.name
}

output "acr_login_server" {
  description = "→ GitHub Variable: ACR_LOGIN_SERVER"
  value       = module.acr.resource.login_server
}

output "ai_services_endpoint" {
  description = "→ GitHub Secret: AZURE_AI_SERVICES_ENDPOINT"
  value       = module.ai_services.resource.endpoint
}

output "ai_services_key" {
  description = "→ GitHub Secret: AZURE_AI_SERVICES_KEY"
  value       = module.ai_services.resource.primary_access_key
  sensitive   = true
}
