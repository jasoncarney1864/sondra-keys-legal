# Azure Container Apps Deployment - Quick Start

## What Was Created

Complete Bicep infrastructure for deploying to Azure Container Apps:

```
infra/
├── main.bicep                       # Main orchestration template
├── main.parameters.json             # Configuration parameters
├── deploy.ps1                       # Automated deployment script
├── README.md                        # Comprehensive deployment guide
└── modules/
    ├── monitoring.bicep             # Log Analytics + App Insights
    ├── container-registry.bicep     # Azure Container Registry
    ├── postgresql.bicep             # PostgreSQL Flexible Server
    ├── container-apps-env.bicep     # Container Apps Environment
    └── container-app.bicep          # Container App (reusable)
```

**Dockerfiles:**
- `backend/Dockerfile` - Already exists, production-ready ✓
- `frontend/Dockerfile` - Created (nginx-based, optimized)
- `.dockerignore` files - Created for both

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Azure Subscription                       │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Container Apps Environment                 │ │
│  │                                                          │ │
│  │  ┌─────────────────┐      ┌──────────────────┐         │ │
│  │  │   Frontend CA   │      │    Backend CA    │         │ │
│  │  │   (React/Vite)  │◄────►│    (FastAPI)     │         │ │
│  │  │   Port 80       │      │    Port 8000     │         │ │
│  │  │   1-5 replicas  │      │    1-3 replicas  │         │ │
│  │  └─────────────────┘      └──────────────────┘         │ │
│  │          │                         │                     │ │
│  └──────────┼─────────────────────────┼────────────────────┘ │
│             │                         │                       │
│             └─────────┬───────────────┘                       │
│                       │                                       │
│  ┌────────────────────▼─────────────────────────────┐        │
│  │           Azure Container Registry               │        │
│  │  (Stores backend & frontend Docker images)      │        │
│  └──────────────────────────────────────────────────┘        │
│                                                               │
│  Backend connects to:                                        │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ PostgreSQL       │  │ Cognitive Search │ (existing)      │
│  │ Flexible Server  │  │ + Blob Storage   │                 │
│  │ (New)            │  │ + Doc Intel      │                 │
│  └──────────────────┘  │ + Foundry        │                 │
│                        └──────────────────┘                  │
│                                                               │
│  ┌──────────────────────────────────────────────────┐        │
│  │        Monitoring (Log Analytics + App Insights)  │        │
│  └──────────────────────────────────────────────────┘        │
└───────────────────────────────────────────────────────────────┘
```

## Before You Deploy

### 1. Prerequisites Checklist

- [ ] Azure CLI installed and authenticated
- [ ] Docker Desktop running
- [ ] GPT-5 Global Standard quota approved in Foundry
- [ ] Existing resources ready:
  - [ ] Cognitive Search service name
  - [ ] Blob Storage account name
  - [ ] Document Intelligence endpoint
  - [ ] Foundry GPT-5 deployment name
  - [ ] All API keys collected

### 2. Update Configuration

Edit `infra/main.parameters.json`:

```json
{
  "searchServiceName": { "value": "YOUR_SEARCH_SERVICE" },
  "storageAccountName": { "value": "yourstorageaccount" },
  "documentIntelligenceEndpoint": { "value": "https://your-doc-intel.cognitiveservices.azure.com/" },
  "openAIDeploymentName": { "value": "your-gpt5-deployment-name" }
}
```

### 3. Choose Secret Management

**Option A: Azure Key Vault (Recommended for Production)**
```powershell
# Create Key Vault
az keyvault create --name "kv-sondra-legal" --resource-group "rg-shared" --location "eastus"

# Store secrets
az keyvault secret set --vault-name "kv-sondra-legal" --name "database-admin-password" --value "STRONG_PASSWORD"
az keyvault secret set --vault-name "kv-sondra-legal" --name "search-api-key" --value "YOUR_SEARCH_KEY"
az keyvault secret set --vault-name "kv-sondra-legal" --name "storage-connection-string" --value "YOUR_CONN_STRING"
az keyvault secret set --vault-name "kv-sondra-legal" --name "document-intelligence-key" --value "YOUR_KEY"
az keyvault secret set --vault-name "kv-sondra-legal" --name "openai-api-key" --value "YOUR_FOUNDRY_KEY"
```

Then update `main.parameters.json` with Key Vault references (see template).

**Option B: Direct Parameters (Dev/Testing Only)**
```powershell
.\infra\deploy.ps1 -Environment dev `
  -DatabasePassword "Pass123!" `
  -SearchApiKey "your-key" `
  -StorageConnectionString "conn-string" `
  -DocumentIntelligenceApiKey "your-key" `
  -OpenAIApiKey "your-foundry-key"
```

## Deploy in 3 Steps

### Step 1: Deploy Infrastructure

```powershell
cd infra
.\deploy.ps1 -Environment dev
```

This will:
1. ✓ Build Docker images
2. ✓ Push to Azure Container Registry
3. ✓ Deploy all infrastructure
4. ✓ Deploy application containers
5. ✓ Output application URLs

**Estimated time:** 10-15 minutes

### Step 2: Verify Deployment

```powershell
# Get URLs from deployment output
# Frontend: https://ca-sondra-legal-frontend-dev.XXX.eastus.azurecontainerapps.io
# Backend: https://ca-sondra-legal-backend-dev.XXX.eastus.azurecontainerapps.io

# Test backend health
curl https://YOUR-BACKEND-URL/api/health

# Open frontend in browser
start https://YOUR-FRONTEND-URL
```

### Step 3: Monitor & Iterate

```powershell
# View backend logs
az containerapp logs show --name ca-sondra-legal-backend-dev --resource-group rg-sondra-legal-dev --follow

# View frontend logs
az containerapp logs show --name ca-sondra-legal-frontend-dev --resource-group rg-sondra-legal-dev --follow
```

## Cost Estimate

**Development Environment:**
- Container Apps: ~$15-30/month (consumption-based)
- PostgreSQL B1ms: ~$12/month
- Container Registry: ~$5/month
- Monitoring: ~$5-10/month
- **Total: ~$40-60/month**

**Production Environment:**
- Scale up PostgreSQL to GP_Gen5_2: ~$100/month
- Increase Container Apps replicas: ~$50-100/month
- **Total: ~$150-250/month**

## Next Steps After Deployment

1. **Database Migrations** (if using Alembic in future)
2. **Custom Domain Setup** (optional)
3. **CI/CD Pipeline** (GitHub Actions)
4. **Monitoring Alerts** (Application Insights)
5. **Backup Strategy** (PostgreSQL automated backups)

## Troubleshooting

**Issue: Container won't start**
```powershell
az containerapp logs show --name ca-sondra-legal-backend-dev --resource-group rg-sondra-legal-dev --tail 100
```

**Issue: Can't connect to database**
- Check firewall rules in PostgreSQL resource
- Verify connection string in container app environment variables

**Issue: Frontend can't reach backend**
- Verify `VITE_API_BASE_URL` environment variable in frontend container app
- Check ingress settings on backend container app

## Cleanup

To delete all resources:
```powershell
az group delete --name rg-sondra-legal-dev --yes --no-wait
```

## Additional Resources

- Full documentation: `infra/README.md`
- Azure Container Apps: https://learn.microsoft.com/azure/container-apps/
- Bicep: https://learn.microsoft.com/azure/azure-resource-manager/bicep/

---

**Status:** Ready to deploy once GPT-5 quota is approved! 🚀
