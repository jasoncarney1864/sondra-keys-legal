# Azure Infrastructure Deployment Guide

## Overview

This directory contains Bicep Infrastructure-as-Code (IaC) templates for deploying the Sondra Keys Legal Q&A application to Azure. All resources are configured with **cost optimization for learning/development purposes**.

## Cost Optimization Decisions

✅ **Azure Cognitive Search**: Free tier (dev) or Basic tier (prod)
✅ **Azure App Service**: B1 Basic tier (dev) or B2 Basic tier (prod)
✅ **Static Web Apps**: Free tier
✅ **Storage**: Standard LRS (locally redundant, no geo-redundancy)
✅ **Container Registry**: Basic tier

**Estimated Monthly Cost (Development):**
- Cognitive Search Free: $0 (limited)
- App Service B1: ~$12
- Static Web Apps Free: $0
- Blob Storage: ~$0.50-2 (minimal)
- Document Intelligence: ~$1-5 (pay-per-use)
- **Total: ~$15-20/month**

## Prerequisites

- Azure subscription
- Azure CLI installed (`az` command available)
- Bash (Linux/Mac) or PowerShell (Windows)
- Bicep CLI (installed with latest Azure CLI)

## Deployment

### Option 1: Linux/Mac

```bash
cd infra/bicep
chmod +x deploy.sh
./deploy.sh dev eastus
```

### Option 2: Windows

```cmd
cd infra\bicep
deploy.bat dev eastus
```

### Option 3: Manual Azure CLI

```bash
# Create resource group
az group create \
  --name rg-sondra-keys-legal-dev \
  --location eastus

# Deploy template
az deployment group create \
  --resource-group rg-sondra-keys-legal-dev \
  --template-file main.bicep \
  --parameters location=eastus environment=dev
```

## Template Files

### `main.bicep`
Main infrastructure template containing:
- Azure Cognitive Search (Free/Basic)
- Blob Storage (Standard LRS)
- Document Intelligence
- Container Registry (Basic)
- App Service Plan (B1/B2)
- App Service (Linux/Docker)
- Static Web App (Free)
- Key Vault

### `deploy.bicep`
Subscription-level deployment template that:
- Creates resource group
- Deploys main.bicep to resource group

### `dev.bicepparam` and `prod.bicepparam`
Parameter files for environment-specific configurations.

## Environment Variables

After deployment, export these values for GitHub Actions:

```bash
# Get outputs from deployment
az deployment group show \
  --resource-group rg-sondra-keys-legal-dev \
  --name <deployment-name> \
  --query "properties.outputs" -o json

# Export for GitHub
export AZURE_SEARCH_ENDPOINT=$(az deployment group show --resource-group rg-sondra-keys-legal-dev --query "properties.outputs.searchServiceEndpoint.value" -o tsv)
export AZURE_SEARCH_KEY=$(az deployment group show --resource-group rg-sondra-keys-legal-dev --query "properties.outputs.searchServiceKey.value" -o tsv)
```

## GitHub Actions Integration

After deployment, configure GitHub Secrets:

1. **Secrets** (Settings → Secrets and variables → Actions):
   - `AZURE_SEARCH_KEY` - From deployment outputs
   - `AZURE_SEARCH_ENDPOINT` - From deployment outputs
   - `AZURE_STORAGE_ACCOUNT_NAME` - From deployment outputs
   - `AZURE_CONTAINER_REGISTRY_LOGIN_SERVER` - From deployment outputs

2. **Variables** (Settings → Secrets and variables → Actions):
   - `AZURE_RESOURCE_GROUP` - `rg-sondra-keys-legal-dev`
   - `AZURE_REGION` - `eastus`

## Resource Scaling

As your application grows, easily upgrade to higher tiers:

```bash
# Upgrade Cognitive Search to Standard
az search service update \
  --resource-group rg-sondra-keys-legal-dev \
  --name sondra-keys-search-dev-xxx \
  --sku standard

# Upgrade App Service to B2 or higher
az appservice plan update \
  --resource-group rg-sondra-keys-legal-dev \
  --name sondra-keys-plan-dev \
  --sku B2
```

## Cleanup

To delete all resources and stop incurring charges:

```bash
az group delete \
  --resource-group rg-sondra-keys-legal-dev \
  --yes \
  --no-wait
```

## Troubleshooting

### Deployment Fails with "Storage account name already exists"
Storage account names must be globally unique. The template uses `uniqueString()` to ensure this, but if deployment fails, try:
```bash
az group delete --resource-group rg-sondra-keys-legal-dev --yes --no-wait
az group create --name rg-sondra-keys-legal-dev --location eastus
```

### Cognitive Search Free Tier Limitation
Free tier is limited to 3 indexes and 50MB storage. For production, use Basic tier or higher.

### Static Web App Deployment Fails
Ensure GitHub integration is configured:
1. In Azure Portal, go to Static Web App
2. Click "Configuration"
3. Add GitHub repository details
4. Authorize GitHub app

## References

- [Bicep documentation](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/)
- [Azure Pricing Calculator](https://azure.microsoft.com/en-us/pricing/calculator/)
- [Azure Well-Architected Framework](https://learn.microsoft.com/en-us/azure/architecture/framework/)
