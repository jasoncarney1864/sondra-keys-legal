@description('Azure region for resources')
param location string

@description('Environment name')
param environment string

@description('Tags applied to resources')
param tags object = {}

var acrName = 'acrsondralegal${environment}'

// Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
    publicNetworkAccess: 'Enabled'
  }
}

output registryName string = containerRegistry.name
output registryLoginServer string = containerRegistry.properties.loginServer
output registryId string = containerRegistry.id
