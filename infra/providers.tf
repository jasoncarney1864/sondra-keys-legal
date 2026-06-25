terraform {
  required_version = ">= 1.9.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.116"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.53"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.31"
    }
  }

  # Remote state — Azure AD (OIDC) authentication, no access keys required.
  # Pre-requisite: the storage account and container must exist before running
  # `terraform init`. Create them once with:
  #   az group create -n rg-terraform-state-dev -l eastus
  #   az storage account create -n sttfstate3238 -g rg-terraform-state-dev --sku Standard_LRS
  #   az storage container create -n tfstate --account-name sttfstate3238
  backend "azurerm" {
    resource_group_name  = "rg-terraform-state-dev"
    storage_account_name = "sttfstate3238"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
    use_oidc             = true
  }
}

# ────────────────────────────────────────────────
# Azure Resource Manager
# Credentials are injected via environment variables by GitHub Actions:
#   ARM_CLIENT_ID, ARM_TENANT_ID, ARM_SUBSCRIPTION_ID, ARM_USE_OIDC=true
# ────────────────────────────────────────────────
provider "azurerm" {
  features {
    resource_group {
      # Allow destroying non-empty resource groups in dev
      prevent_deletion_if_contains_resources = false
    }
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }
  use_oidc = true
}

# ────────────────────────────────────────────────
# Azure Active Directory
# ────────────────────────────────────────────────
provider "azuread" {
  use_oidc = true
}

# ────────────────────────────────────────────────
# Kubernetes
# Configured using AKS kube_config after the cluster is created.
#
# ⚠️  Bootstrap order: On the very first run, apply infrastructure only:
#     terraform apply -target=module.aks -target=module.acr -target=azurerm_role_assignment.aks_acr_pull
# Then run `terraform apply` to let Kubernetes resources use the live config.
#
# In production, replace kube_config with an `exec` block using kubelogin
# + Workload Identity for AAD-integrated clusters.
# ────────────────────────────────────────────────
provider "kubernetes" {
  host = try(
    module.aks.resource.kube_config[0].host,
    ""
  )
  client_certificate = try(
    base64decode(module.aks.resource.kube_config[0].client_certificate),
    ""
  )
  client_key = try(
    base64decode(module.aks.resource.kube_config[0].client_key),
    ""
  )
  cluster_ca_certificate = try(
    base64decode(module.aks.resource.kube_config[0].cluster_ca_certificate),
    ""
  )
}
