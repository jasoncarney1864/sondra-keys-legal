metadata description = 'Deploy Azure Infrastructure for Sondra Keys Legal QA'

targetScope = 'subscription'

param location string = 'eastus'
param resourceGroupName string = 'rg-sondra-keys-legal-dev'
param environment string = 'dev'

// Create resource group
resource resourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: resourceGroupName
  location: location
  tags: {
    environment: environment
    app: 'sondra-keys'
    createdDate: utcNow('u')
  }
}

// Deploy main infrastructure template to resource group
module infrastructure './main.bicep' = {
  scope: resourceGroup
  name: 'infrastructure-deployment'
  params: {
    location: location
    environment: environment
    appName: 'sondra-keys'
    searchTierDev: 'free'
    appServiceSkuDev: 'B1'
  }
}

// Outputs
output resourceGroupId string = resourceGroup.id
output resourceGroupName string = resourceGroup.name
output infrastructureOutputs object = infrastructure.outputs
