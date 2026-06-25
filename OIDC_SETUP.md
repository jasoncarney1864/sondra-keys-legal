# DevSecOps: OIDC Authentication Setup

## Overview

This project uses **OpenID Connect (OIDC)** Workload Identity Federation for GitHub Actions → Azure authentication. This eliminates the need for long-lived credentials stored as secrets.

## Architecture

```
GitHub Actions Workflow
        ↓
  Request OIDC Token
        ↓
GitHub OIDC Provider
        ↓
Exchange for Azure Access Token
        ↓
Microsoft Entra ID (with OIDC Trusted Publisher)
        ↓
Azure Resources (RBAC)
```

## Setup Steps

### Step 1: Create Azure App Registration

```bash
# Login to Azure
az login

# Set variables
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
RESOURCE_GROUP="sondra-keys-rg"
APP_NAME="sondra-keys-github-oidc"

# Create App Registration
APP=$(az ad app create --display-name $APP_NAME)
APP_ID=$(echo $APP | jq -r '.appId')
OBJECT_ID=$(echo $APP | jq -r '.id')

echo "App ID (Client ID): $APP_ID"
echo "Object ID: $OBJECT_ID"
```

### Step 2: Create Federated Credentials

Federated credentials allow GitHub to authenticate without storing secrets.

```bash
# For main branch deployments (production)
az ad app federated-credential create \
  --id $OBJECT_ID \
  --parameters '{
    "name": "github-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:YOUR_ORG/sondra-keys-legal:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'

# For develop branch deployments (staging)
az ad app federated-credential create \
  --id $OBJECT_ID \
  --parameters '{
    "name": "github-develop",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:YOUR_ORG/sondra-keys-legal:ref:refs/heads/develop",
    "audiences": ["api://AzureADTokenExchange"]
  }'

# For pull request workflows
az ad app federated-credential create \
  --id $OBJECT_ID \
  --parameters '{
    "name": "github-pr",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:YOUR_ORG/sondra-keys-legal:pull_request",
    "audiences": ["api://AzureADTokenExchange"]
  }'

echo "Federated credentials created successfully"
```

### Step 3: Assign RBAC Roles

```bash
# Create a service principal for the app (required before assigning roles)
az ad sp create --id $APP_ID

# Get the principal ID
PRINCIPAL_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

# Assign roles to the app at subscription level
az role assignment create \
  --assignee-object-id $PRINCIPAL_ID \
  --role "Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION_ID"

# For more fine-grained control, assign specific roles:
# Assign Container Registry Push role for publishing images
az role assignment create \
  --assignee-object-id $PRINCIPAL_ID \
  --role "AcrPush" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

# Assign Storage Blob Data Contributor for blob operations
az role assignment create \
  --assignee-object-id $PRINCIPAL_ID \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

# Assign Cognitive Services User for Content Understanding
az role assignment create \
  --assignee-object-id $PRINCIPAL_ID \
  --role "Cognitive Services User" \
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

echo "RBAC roles assigned successfully"
```

### Step 4: Create GitHub Secrets and Variables

In your GitHub repository:

**Secrets** (Settings → Secrets and variables → Actions):
- `AZURE_CLIENT_ID` → (value: $APP_ID)
- `AZURE_TENANT_ID` → (value: $TENANT_ID)
- `AZURE_SUBSCRIPTION_ID` → (value: $SUBSCRIPTION_ID)

**Variables** (Settings → Secrets and variables → Actions):
- `AZURE_RESOURCE_GROUP` → `sondra-keys-rg`
- `AZURE_REGION` → `eastus`
- `CDN_ENDPOINT` → (optional) your CDN endpoint name - only if using Azure CDN
- `CDN_PROFILE` → (optional) your CDN profile name - only if using Azure CDN

```bash
# Set these via GitHub CLI (gh):
gh secret set AZURE_CLIENT_ID --body $APP_ID
gh secret set AZURE_TENANT_ID --body $TENANT_ID
gh secret set AZURE_SUBSCRIPTION_ID --body $SUBSCRIPTION_ID

gh variable set AZURE_RESOURCE_GROUP --body "rg-sondra-keys-legal-dev"
gh variable set AZURE_REGION --body "eastus"
```

### Step 5: Verify Setup

```bash
# Test the OIDC token creation (manual verification)
# Create a test workflow that echoes the token (for debugging only)

# Verify federated credentials are configured
az ad app federated-credential list --id $OBJECT_ID --query '[].{name:name, subject:subject}'

# Verify RBAC roles
az role assignment list --assignee $PRINCIPAL_ID --output table
```

## GitHub Actions Workflow Usage

### Example: OIDC Login in Workflow

```yaml
- name: Azure Login (OIDC)
  uses: azure/login@v2
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

- name: Deploy Resources
  run: |
    az containerapp create \
      --resource-group ${{ vars.AZURE_RESOURCE_GROUP }} \
      --name my-app
```

### Required Permissions in Workflow

```yaml
jobs:
  deploy:
    permissions:
      id-token: write      # REQUIRED for OIDC token generation
      contents: read       # To checkout code
      # Add other permissions as needed
```

## Security Benefits

✅ **No Long-Lived Credentials** - Tokens are short-lived (1 hour max)  
✅ **Workload Identity** - GitHub Actions authenticated as specific workload  
✅ **Repository Scoped** - Credentials tied to specific repo/branch  
✅ **Audit Trail** - All operations logged in Azure Activity Log  
✅ **Automated Rotation** - Tokens automatically renewed by Azure  
✅ **Least Privilege** - RBAC roles restrict access to minimum needed  

## Troubleshooting

### "Authorization failed" in Actions

- Verify federated credential `subject` matches repo path exactly
- Format: `repo:OWNER/REPO:ref:refs/heads/BRANCH`
- Check RBAC roles are assigned to the App Registration's service principal

### "OIDC token could not be generated"

- Ensure job has `permissions.id-token: write`
- Verify GitHub Actions has access to OIDC (check organization settings)
- Check runner has network access to token.actions.githubusercontent.com

### "Federated credential mismatch"

- PR workflows use `pull_request` subject
- Branch deployments use `ref:refs/heads/BRANCH` subject
- Environment deployments use `environment:ENV_NAME` subject

## Reference: Federated Credential Subjects

```
# Main branch
repo:ORG/REPO:ref:refs/heads/main

# Pull requests
repo:ORG/REPO:pull_request

# Specific environment
repo:ORG/REPO:environment:production

# All branches matching pattern
repo:ORG/REPO:ref:refs/heads/release-*

# All tags
repo:ORG/REPO:ref:refs/tags/*
```

## References

- [Microsoft: Configure OIDC in Azure for GitHub Actions](https://docs.microsoft.com/en-us/azure/developer/github/connect-from-azure?tabs=linux%2Cwindows)
- [GitHub: OIDC Token Issuance](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)
- [Azure RBAC Roles Reference](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles)

## Post-Setup Validation

Run this command to ensure everything is configured correctly:

```bash
# Test OIDC authentication (from GitHub Actions workflow)
az account show

# Verify you can create resources
az resource list --resource-group rg-sondra-keys-legal-dev
```

Once verified, your GitHub Actions workflows can securely deploy to Azure without storing credentials!
