# Sondra Keys Legal - Azure Container Apps Deployment

This directory contains Bicep Infrastructure as Code (IaC) templates for deploying the Sondra Keys Legal application to Azure Container Apps.

## Architecture

The deployment creates:

- **Container Apps Environment**: Hosting platform for both frontend and backend
- **Backend Container App**: FastAPI application with PostgreSQL database
- **Frontend Container App**: React SPA serving the UI
- **PostgreSQL Flexible Server**: Production database
- **Container Registry**: Stores Docker images
- **Log Analytics + Application Insights**: Monitoring and diagnostics

## Prerequisites

1. **Azure CLI** installed and authenticated
   ```powershell
   az login
   az account set --subscription "YOUR_SUBSCRIPTION_ID"
   ```

2. **Bicep CLI** (included with Azure CLI)
   ```powershell
   az bicep version
   ```

3. **Docker** for building container images
   ```powershell
   docker --version
   ```

4. **Existing Azure Resources**:
   - Azure Cognitive Search service with `documents` index
   - Azure Blob Storage account with `documents` container
   - Azure Document Intelligence resource
   - Microsoft Foundry project with GPT-5 deployment

5. **Azure Key Vault** (optional but recommended for secrets)

## Configuration

### 1. Update Parameters File

Edit `main.parameters.json` and replace placeholders:

```json
{
  "searchServiceName": { "value": "your-search-service" },
  "storageAccountName": { "value": "yourstorageaccount" },
  "documentIntelligenceEndpoint": { "value": "https://your-doc-intel.cognitiveservices.azure.com/" },
  "openAIDeploymentName": { "value": "your-gpt5-deployment" }
}
```

### 2. Store Secrets in Key Vault (Recommended)

```powershell
# Create Key Vault
az keyvault create \
  --name "kv-sondra-legal" \
  --resource-group "rg-sondra-legal-shared" \
  --location "eastus"

# Store secrets
az keyvault secret set --vault-name "kv-sondra-legal" --name "database-admin-password" --value "YOUR_STRONG_PASSWORD"
az keyvault secret set --vault-name "kv-sondra-legal" --name "search-api-key" --value "YOUR_SEARCH_KEY"
az keyvault secret set --vault-name "kv-sondra-legal" --name "storage-connection-string" --value "YOUR_STORAGE_CONN_STRING"
az keyvault secret set --vault-name "kv-sondra-legal" --name "document-intelligence-key" --value "YOUR_DOC_INTEL_KEY"
az keyvault secret set --vault-name "kv-sondra-legal" --name "openai-api-key" --value "YOUR_FOUNDRY_API_KEY"
```

Update `main.parameters.json` with Key Vault references (see template).

### 3. Alternative: Use Local Secrets (Dev Only)

For quick development deployments, pass secrets directly:

```powershell
.\deploy.ps1 `
  -Environment "dev" `
  -DatabasePassword "YourPassword123!" `
  -SearchApiKey "your-key" `
  -StorageConnectionString "DefaultEndpointsProtocol=https;..." `
  -DocumentIntelligenceApiKey "your-key" `
  -OpenAIApiKey "your-foundry-key"
```

## Deployment

### Option 1: Using deploy.ps1 Script (Recommended)

```powershell
cd infra
.\deploy.ps1 -Environment dev
```

The script will:
1. Build Docker images for frontend and backend
2. Push images to Azure Container Registry
3. Deploy infrastructure using Bicep
4. Output application URLs

### Option 2: Manual Deployment

```powershell
# 1. Deploy infrastructure
az deployment sub create \
  --location eastus \
  --template-file main.bicep \
  --parameters main.parameters.json

# 2. Build and push images
$ACR_NAME = "acrsondralegaldev"
az acr login --name $ACR_NAME

# Backend
docker build -t $ACR_NAME.azurecr.io/sondra-legal-backend:latest ./backend
docker push $ACR_NAME.azurecr.io/sondra-legal-backend:latest

# Frontend
docker build -t $ACR_NAME.azurecr.io/sondra-legal-frontend:latest ./frontend
docker push $ACR_NAME.azurecr.io/sondra-legal-frontend:latest

# 3. Redeploy with new images
az deployment sub create \
  --location eastus \
  --template-file main.bicep \
  --parameters main.parameters.json \
  --parameters imageTag=latest
```

## Post-Deployment

### 1. Run Database Migrations

```powershell
# Get backend container app name
$BACKEND_APP = az containerapp list --query "[?contains(name, 'backend')].name" -o tsv

# Execute migration
az containerapp exec \
  --name $BACKEND_APP \
  --resource-group rg-sondra-legal-dev \
  --command "python -m alembic upgrade head"
```

### 2. Verify Deployment

```powershell
# Get application URLs
az deployment sub show \
  --name main \
  --query 'properties.outputs.frontendUrl.value' -o tsv

az deployment sub show \
  --name main \
  --query 'properties.outputs.backendUrl.value' -o tsv
```

Visit the frontend URL in your browser.

### 3. Monitor Application

```powershell
# View logs
az containerapp logs show \
  --name ca-sondra-legal-backend-dev \
  --resource-group rg-sondra-legal-dev \
  --follow

# View metrics in Application Insights
az portal show --query 'id' --resource-group rg-sondra-legal-dev --name appi-sondra-legal-dev
```

## Scaling

Container Apps auto-scale based on HTTP traffic (default: 1-3 replicas for backend, 1-5 for frontend).

To adjust scaling:

```powershell
az containerapp update \
  --name ca-sondra-legal-backend-dev \
  --resource-group rg-sondra-legal-dev \
  --min-replicas 2 \
  --max-replicas 10
```

## Cost Estimation

**Development environment** (~$50-80/month):
- Container Apps: ~$15-30/month (consumption-based)
- PostgreSQL B1ms: ~$12/month
- Container Registry Basic: ~$5/month
- Log Analytics: ~$2-10/month
- Application Insights: ~$2-5/month

**Production environment** (~$150-300/month):
- Scale up PostgreSQL to General Purpose
- Enable geo-redundancy
- Increase Container Apps replicas

## Troubleshooting

### Container App Won't Start

```powershell
# Check logs
az containerapp logs show --name ca-sondra-legal-backend-dev --resource-group rg-sondra-legal-dev --tail 100

# Check revision status
az containerapp revision list --name ca-sondra-legal-backend-dev --resource-group rg-sondra-legal-dev
```

### Database Connection Issues

```powershell
# Test connectivity from Container App
az containerapp exec \
  --name ca-sondra-legal-backend-dev \
  --resource-group rg-sondra-legal-dev \
  --command "psql -h HOSTNAME -U USERNAME -d sondra_legal"
```

### Image Build Failures

```powershell
# Build locally with verbose output
docker build --progress=plain -t test-backend ./backend
```

## Cleanup

To delete all resources:

```powershell
az group delete --name rg-sondra-legal-dev --yes --no-wait
```

## Additional Resources

- [Azure Container Apps Documentation](https://learn.microsoft.com/azure/container-apps/)
- [Bicep Documentation](https://learn.microsoft.com/azure/azure-resource-manager/bicep/)
- [PostgreSQL on Azure](https://learn.microsoft.com/azure/postgresql/)
