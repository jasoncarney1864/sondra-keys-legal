targetScope = 'resourceGroup'

@description('Policy definition resource ID used for tag requirement enforcement')
param policyDefinitionId string

resource requireEnvironmentTagAssignment 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'pa-sondra-require-tag-environment'
  properties: {
    displayName: 'Require Environment tag'
    description: 'Enforces Environment tag on new resources.'
    policyDefinitionId: policyDefinitionId
    parameters: {
      tagName: {
        value: 'Environment'
      }
    }
  }
}

resource requireProjectTagAssignment 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'pa-sondra-require-tag-project'
  properties: {
    displayName: 'Require Project tag'
    description: 'Enforces Project tag on new resources.'
    policyDefinitionId: policyDefinitionId
    parameters: {
      tagName: {
        value: 'Project'
      }
    }
  }
}

resource requireOwnerTagAssignment 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'pa-sondra-require-tag-owner'
  properties: {
    displayName: 'Require Owner tag'
    description: 'Enforces Owner tag on new resources.'
    policyDefinitionId: policyDefinitionId
    parameters: {
      tagName: {
        value: 'Owner'
      }
    }
  }
}

resource requireCreatorTagAssignment 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'pa-sondra-require-tag-creator'
  properties: {
    displayName: 'Require Creator tag'
    description: 'Enforces Creator tag on new resources.'
    policyDefinitionId: policyDefinitionId
    parameters: {
      tagName: {
        value: 'Creator'
      }
    }
  }
}

resource requireDateCreatedTagAssignment 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'pa-sondra-require-tag-datecreated'
  properties: {
    displayName: 'Require DateCreated tag'
    description: 'Enforces DateCreated tag on new resources.'
    policyDefinitionId: policyDefinitionId
    parameters: {
      tagName: {
        value: 'DateCreated'
      }
    }
  }
}
