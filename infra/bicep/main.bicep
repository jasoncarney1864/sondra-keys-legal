metadata description = 'Sondra Keys Legal Q&A - Main Infrastructure as Code'

param location string = resourceGroup().location
param environment string = 'dev'
param appName string = 'sondra-keys'

// Cost-optimized SKU selection based on environment
param searchTierDev string = 'free'  // Free tier for development
param searchTierProd string = 'basic'  // Basic tier for production
param appServiceSkuDev string = 'B1'  // Basic tier for development
param appServiceSkuProd string = 'B2'  // Basic tier for production

var uniqueSuffix = uniqueString(resourceGroup().id)
var searchServiceName = '${appName}-search-${environment}-${uniqueSuffix}'
var storageAccountName = '${replace(appName, '-', '')}${environment}${uniqueSuffix}'
var appServicePlanName = '${appName}-plan-${environment}'
var appServiceName = '${appName}-api-${environment}'
var staticWebAppName = '${appName}-web-${environment}'
var containerRegistryName = '${replace(appName, '-', '')}${environment}${uniqueSuffix}'
var documentIntelligenceName = '${appName}-docint-${environment}'
var keyVaultName = '${appName}-kv-${environment}-${uniqueSuffix}'

// Select appropriate search tier based on environment
var searchTier = environment == 'prod' ? searchTierProd : searchTierDev

// ============================================================================
// Cognitive Search (Cost-optimized: Free tier for dev, Basic for prod)
// ============================================================================
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchServiceName
  location: location
  sku: {
    name: searchTier  // Free or Basic tier only
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'Enabled'
  }
  tags: {
    environment: environment
    app: appName
    costOptimization: 'free-basic-tier-only'
  }
}

// ============================================================================
// Blob Storage for Documents (Cost-optimized: Standard LRS)
// ============================================================================
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'  // Locally redundant, cheapest option
  }
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
  }
  tags: {
    environment: environment
    app: appName
    costOptimization: 'standard-lrs'
  }
}

// Storage container for documents
resource blobContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${storageAccount.name}/default/documents'
  properties: {
    publicAccess: 'None'
  }
}

// ============================================================================
// Document Intelligence (OCR/Content Understanding)
// ============================================================================
resource documentIntelligence 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: documentIntelligenceName
  location: location
  kind: 'DocumentIntelligence'
  sku: {
    name: 'S0'  // Standard tier
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
  tags: {
    environment: environment
    app: appName
  }
}

// ============================================================================
// Container Registry (for backend Docker images)
// ============================================================================
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: containerRegistryName
  location: location
  sku: {
    name: 'Basic'  // Cost-optimized: Basic tier
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: 'Enabled'
  }
  tags: {
    environment: environment
    app: appName
    costOptimization: 'basic-tier'
  }
}

// ============================================================================
// App Service Plan (Cost-optimized: B1 tier for dev/staging)
// ============================================================================
resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: appServicePlanName
  location: location
  kind: 'linux'
  sku: {
    name: environment == 'prod' ? appServiceSkuProd : appServiceSkuDev
    capacity: 1
  }
  properties: {
    reserved: true  // For Linux containers
  }
  tags: {
    environment: environment
    app: appName
    costOptimization: 'b1-basic-tier'
  }
}

// ============================================================================
// App Service (Backend API)
// ============================================================================
resource appService 'Microsoft.Web/sites@2023-01-01' = {
  name: appServiceName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    siteConfig: {
      linuxFxVersion: 'DOCKER|${containerRegistry.properties.loginServer}/backend:latest'
      appSettings: [
        {
          name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE'
          value: 'false'
        }
        {
          name: 'DOCKER_REGISTRY_SERVER_URL'
          value: 'https://${containerRegistry.properties.loginServer}'
        }
        {
          name: 'DOCKER_ENABLE_CI'
          value: 'true'
        }
      ]
    }
    httpsOnly: true
  }
  tags: {
    environment: environment
    app: appName
  }
}

// ============================================================================
// Static Web App (Frontend) - FREE TIER
// ============================================================================
resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Free'  // Cost-optimized: Free tier
    tier: 'Free'
  }
  properties: {
    provider: 'GitHub'
    branch: 'main'
    buildProperties: {
      appLocation: 'frontend'
      outputLocation: 'dist'
    }
  }
  tags: {
    environment: environment
    app: appName
    costOptimization: 'free-tier'
  }
}

// ============================================================================
// Key Vault for Secrets
// ============================================================================
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    accessPolicies: [
      {
        tenantId: subscription().tenantId
        objectId: appService.identity.principalId
        permissions: {
          secrets: ['get', 'list']
        }
      }
    ]
    enableRbacAuthorization: false
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
  tags: {
    environment: environment
    app: appName
  }
}

// ============================================================================
// Outputs
// ============================================================================
output searchServiceEndpoint string = 'https://${searchService.name}.search.windows.net'
output searchServiceKey string = listAdminKeys(searchService.id, '2023-11-01').primaryKey
output storageAccountName string = storageAccount.name
output containerRegistryLoginServer string = containerRegistry.properties.loginServer
output appServiceUrl string = 'https://${appService.properties.defaultHostName}'
output staticWebAppUrl string = staticWebApp.properties.defaultHostname
output keyVaultUri string = keyVault.properties.vaultUri
