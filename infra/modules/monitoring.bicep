@description('Azure region for resources')
param location string

@description('Environment name')
param environment string

@description('Enable baseline alert rules for backend health and latency')
param enableAlerts bool = true

@description('Number of backend 5xx requests in alert window that triggers a high-severity alert')
param backend5xxThreshold int = 15

@description('Number of backend exceptions in alert window that triggers a high-severity alert')
param backendExceptionThreshold int = 20

@description('P95 backend request latency threshold in milliseconds')
param backendP95LatencyMsThreshold int = 3000

var logAnalyticsName = 'log-sondra-legal-${environment}'
var appInsightsName = 'appi-sondra-legal-${environment}'

// Log Analytics Workspace
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    RetentionInDays: 30
  }
}

resource backend5xxSpikeAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (enableAlerts) {
  name: 'alert-sondra-legal-backend-5xx-spike-${environment}'
  location: location
  kind: 'LogAlert'
  properties: {
    description: 'Backend API 5xx spike detected in AppRequests telemetry.'
    displayName: 'Sondra Backend 5xx Spike (${environment})'
    enabled: true
    severity: 1
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [
      appInsights.id
    ]
    skipQueryValidation: true
    criteria: {
      allOf: [
        {
          query: '''
AppRequests
| where TimeGenerated > ago(15m)
| where Url has "/api/"
| where ResultCode startswith "5"
'''
          timeAggregation: 'Count'
          operator: 'GreaterThanOrEqual'
          threshold: backend5xxThreshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: []
      customProperties: {
        alertType: 'backend-5xx-spike'
        environment: environment
      }
    }
    autoMitigate: true
  }
}

resource backendExceptionSpikeAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (enableAlerts) {
  name: 'alert-sondra-legal-backend-exception-spike-${environment}'
  location: location
  kind: 'LogAlert'
  properties: {
    description: 'Backend exception spike detected in AppExceptions telemetry.'
    displayName: 'Sondra Backend Exception Spike (${environment})'
    enabled: true
    severity: 2
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [
      appInsights.id
    ]
    skipQueryValidation: true
    criteria: {
      allOf: [
        {
          query: '''
AppExceptions
| where TimeGenerated > ago(15m)
| where AppRoleName has "backend" or tostring(Properties) has "/api/"
'''
          timeAggregation: 'Count'
          operator: 'GreaterThanOrEqual'
          threshold: backendExceptionThreshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: []
      customProperties: {
        alertType: 'backend-exception-spike'
        environment: environment
      }
    }
    autoMitigate: true
  }
}

resource backendP95LatencyAlert 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = if (enableAlerts) {
  name: 'alert-sondra-legal-backend-p95-latency-${environment}'
  location: location
  kind: 'LogAlert'
  properties: {
    description: 'Backend API p95 latency is above threshold.'
    displayName: 'Sondra Backend P95 Latency (${environment})'
    enabled: true
    severity: 2
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [
      appInsights.id
    ]
    skipQueryValidation: true
    criteria: {
      allOf: [
        {
          query: '''
AppRequests
| where TimeGenerated > ago(15m)
| where Url has "/api/"
| summarize p95LatencyMs = percentile(DurationMs, 95)
'''
          metricMeasureColumn: 'p95LatencyMs'
          timeAggregation: 'Maximum'
          operator: 'GreaterThanOrEqual'
          threshold: backendP95LatencyMsThreshold
          failingPeriods: {
            numberOfEvaluationPeriods: 1
            minFailingPeriodsToAlert: 1
          }
        }
      ]
    }
    actions: {
      actionGroups: []
      customProperties: {
        alertType: 'backend-p95-latency'
        environment: environment
      }
    }
    autoMitigate: true
  }
}

output logAnalyticsWorkspaceId string = logAnalytics.id
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey
output appInsightsConnectionString string = appInsights.properties.ConnectionString
