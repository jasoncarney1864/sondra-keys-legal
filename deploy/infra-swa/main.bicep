targetScope = 'resourceGroup'

@description('Environment name used for naming resources.')
param environmentName string

@description('Deployment location for the Static Web App.')
param location string = resourceGroup().location

@description('Optional tags to apply to all resources.')
param tags object = {}

var serviceName = 'web'
var staticWebAppNameBase = toLower(replace('swa-${environmentName}', '_', '-'))
var staticWebAppName = take('${staticWebAppNameBase}-${uniqueString(resourceGroup().id)}', 59)

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticWebAppName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  tags: union(tags, {
    'azd-service-name': serviceName
  })
  properties: {}
}

output AZURE_STATIC_WEB_APP_NAME string = staticWebApp.name
output AZURE_STATIC_WEB_APP_DEFAULT_HOSTNAME string = staticWebApp.properties.defaultHostname
