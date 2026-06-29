targetScope = 'subscription'

@description('Environment name (dev, staging, prod)')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'dev'

@description('Primary Azure region for resources')
param location string = 'eastus'

@description('Resource group name')
param resourceGroupName string = 'rg-sondra-legal-${environment}'

@description('Container image tag to deploy')
param imageTag string = 'latest'

@description('When false, skip frontend/backend container app deployment (bootstrap mode).')
param deployApps bool = true

@description('Existing Azure Cognitive Search service name')
param searchServiceName string

@description('Existing Azure Cognitive Search index name')
param searchIndexName string = 'documents'

@description('Existing Azure Blob Storage account name')
param storageAccountName string

@description('Existing Azure Blob Storage container name')
param storageContainerName string = 'documents'

@description('Existing Azure Document Intelligence endpoint')
param documentIntelligenceEndpoint string

@description('Azure OpenAI endpoint (Foundry)')
param openAIEndpoint string

@description('Azure OpenAI deployment name')
param openAIDeploymentName string

@description('Azure OpenAI API version')
param openAIApiVersion string = '2024-10-21'

@description('Database administrator username')
@secure()
param databaseAdminUsername string

@description('Database administrator password')
@secure()
param databaseAdminPassword string

@description('Azure Cognitive Search API key')
@secure()
param searchApiKey string

@description('Azure Blob Storage connection string')
@secure()
param storageConnectionString string

@description('Azure Document Intelligence API key')
@secure()
param documentIntelligenceApiKey string

@description('Azure OpenAI API key')
@secure()
param openAIApiKey string

@description('Shared API key used by frontend reverse proxy and backend auth')
@secure()
param securityApiKey string

@description('Number of backend 5xx requests in alert window that triggers alert')
param backend5xxThreshold int = 15

@description('Number of backend exceptions in alert window that triggers alert')
param backendExceptionThreshold int = 20

@description('P95 backend latency threshold in milliseconds for alerting')
param backendP95LatencyMsThreshold int = 3000

@description('Email addresses for SRE on-call monitoring action group')
param sreOnCallEmailAddresses array = []

@description('Email addresses for application team on-call monitoring action group')
param appOnCallEmailAddresses array = []

@description('Optional existing action group resource IDs to include in monitoring alerts')
param additionalAlertActionGroupResourceIds array = []

var storageAccountKey = first(split(last(split(storageConnectionString, 'AccountKey=')), ';'))
var appEnvironment = environment == 'prod' ? 'production' : (environment == 'staging' ? 'staging' : 'development')
var databasePasswordEncoded = uriComponent(databaseAdminPassword)

// Resource group
resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: resourceGroupName
  location: location
  tags: {
    environment: environment
    project: 'sondra-keys-legal'
    managedBy: 'bicep'
  }
}

// Monitoring module
module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring-deployment'
  params: {
    location: location
    environment: environment
    enableAlerts: deployApps
    backend5xxThreshold: backend5xxThreshold
    backendExceptionThreshold: backendExceptionThreshold
    backendP95LatencyMsThreshold: backendP95LatencyMsThreshold
    sreOnCallEmailAddresses: sreOnCallEmailAddresses
    appOnCallEmailAddresses: appOnCallEmailAddresses
    additionalAlertActionGroupResourceIds: additionalAlertActionGroupResourceIds
  }
}

// Container Registry module
module containerRegistry 'modules/container-registry.bicep' = {
  scope: rg
  name: 'acr-deployment'
  params: {
    location: location
    environment: environment
  }
}

// PostgreSQL module
module database 'modules/postgresql.bicep' = {
  scope: rg
  name: 'postgresql-deployment'
  params: {
    location: location
    environment: environment
    administratorLogin: databaseAdminUsername
    administratorPassword: databaseAdminPassword
  }
}

// Container Apps Environment module
module containerAppsEnv 'modules/container-apps-env.bicep' = {
  scope: rg
  name: 'containerapp-env-deployment'
  params: {
    location: location
    environment: environment
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
  }
}

// Backend Container App
module backendApp 'modules/container-app.bicep' = if (deployApps) {
  scope: rg
  name: 'backend-app-deployment'
  params: {
    location: location
    environment: environment
    appName: 'backend'
    containerAppsEnvironmentId: containerAppsEnv.outputs.environmentId
    containerRegistryName: containerRegistry.outputs.registryName
    containerImage: '${containerRegistry.outputs.registryLoginServer}/sondra-legal-backend:${imageTag}'
    targetPort: 8000
    minReplicas: 1
    maxReplicas: 3
    environmentVariables: [
      {
        name: 'DB_DATABASE_URL'
        value: 'postgresql+asyncpg://${databaseAdminUsername}:${databasePasswordEncoded}@${database.outputs.fqdn}:5432/sondra_legal'
      }
      {
        name: 'AI_SEARCH_SERVICE_NAME'
        value: searchServiceName
      }
      {
        name: 'AZURE_SEARCH_SERVICE_NAME'
        value: searchServiceName
      }
      {
        name: 'AI_SEARCH_INDEX_NAME'
        value: searchIndexName
      }
      {
        name: 'AI_SEARCH_API_KEY'
        secretRef: 'search-api-key'
      }
      {
        name: 'AZURE_SEARCH_API_KEY'
        secretRef: 'search-api-key'
      }
      {
        name: 'AZURE_STORAGE_CONNECTION_STRING'
        secretRef: 'storage-connection-string'
      }
      {
        name: 'AZURE_BLOB_ACCOUNT_NAME'
        value: storageAccountName
      }
      {
        name: 'AZURE_BLOB_ACCOUNT_KEY'
        secretRef: 'blob-account-key'
      }
      {
        name: 'AZURE_BLOB_CONTAINER_NAME'
        value: storageContainerName
      }
      {
        name: 'AZURE_STORAGE_CONTAINER_NAME'
        value: storageContainerName
      }
      {
        name: 'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT'
        value: documentIntelligenceEndpoint
      }
      {
        name: 'AZURE_DOCUMENT_INTELLIGENCE_KEY'
        secretRef: 'doc-intelligence-key'
      }
      {
        name: 'AZURE_CONTENT_UNDERSTANDING_ENDPOINT'
        value: documentIntelligenceEndpoint
      }
      {
        name: 'AZURE_CONTENT_UNDERSTANDING_KEY'
        secretRef: 'doc-intelligence-key'
      }
      {
        name: 'AI_OPENAI_ENDPOINT'
        value: openAIEndpoint
      }
      {
        name: 'AI_OPENAI_DEPLOYMENT_NAME'
        value: openAIDeploymentName
      }
      {
        name: 'AI_OPENAI_API_VERSION'
        value: openAIApiVersion
      }
      {
        name: 'AI_OPENAI_API_KEY'
        secretRef: 'openai-api-key'
      }
      {
        name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
        value: monitoring.outputs.appInsightsConnectionString
      }
      {
        name: 'OPENAI_API_KEY'
        secretRef: 'openai-api-key'
      }
      {
        name: 'ENVIRONMENT'
        value: appEnvironment
      }
      {
        name: 'SECURITY_API_KEY'
        secretRef: 'security-api-key'
      }
    ]
    secrets: [
      {
        name: 'search-api-key'
        value: searchApiKey
      }
      {
        name: 'storage-connection-string'
        value: storageConnectionString
      }
      {
        name: 'doc-intelligence-key'
        value: documentIntelligenceApiKey
      }
      {
        name: 'blob-account-key'
        value: storageAccountKey
      }
      {
        name: 'openai-api-key'
        value: openAIApiKey
      }
      {
        name: 'security-api-key'
        value: securityApiKey
      }
    ]
  }
}

// Frontend Container App
module frontendApp 'modules/container-app.bicep' = if (deployApps) {
  scope: rg
  name: 'frontend-app-deployment'
  params: {
    location: location
    environment: environment
    appName: 'frontend'
    containerAppsEnvironmentId: containerAppsEnv.outputs.environmentId
    containerRegistryName: containerRegistry.outputs.registryName
    containerImage: '${containerRegistry.outputs.registryLoginServer}/sondra-legal-frontend:${imageTag}'
    targetPort: 80
    minReplicas: 1
    maxReplicas: 5
    environmentVariables: [
      {
        name: 'BACKEND_URL'
        value: 'https://${backendApp.outputs.fqdn}'
      }
      {
        name: 'API_KEY'
        secretRef: 'frontend-api-key'
      }
    ]
    secrets: [
      {
        name: 'frontend-api-key'
        value: securityApiKey
      }
    ]
  }
}

// Outputs
output resourceGroupName string = rg.name
output frontendUrl string = deployApps ? 'https://${frontendApp.outputs.fqdn}' : ''
output backendUrl string = deployApps ? 'https://${backendApp.outputs.fqdn}' : ''
output containerRegistryLoginServer string = containerRegistry.outputs.registryLoginServer
output databaseHost string = database.outputs.fqdn
