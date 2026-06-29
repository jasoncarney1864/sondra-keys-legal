param(
    [string]$EnvironmentName = "dev",
    [string]$AzureResourceGroup = "rg-sondra-legal-dev",
    [string]$SearchResourceGroup = "rg-terraform-state-dev",
    [string]$SearchServiceName = "sondra-legal-search",
    [string]$StorageResourceGroup = "rg-terraform-state-dev",
    [string]$StorageAccountName = "sttfstate3238",
    [string]$DocIntelResourceGroup = "rg-terraform-state-dev",
    [string]$DocIntelAccountName = "sondra-legal-docintel",
    [string]$OpenAIResourceGroup = "NetworkWatcherRG",
    [string]$OpenAIAccountName = "sondra-legal-project-resource",
    [string]$OpenAIDeploymentName = "gpt-5-mini",
    [string]$OpenAIApiVersion = "2024-10-21",
    [string]$SearchIndexName = "documents",
    [string]$StorageContainerName = "documents",
    [Parameter(Mandatory = $true)]
    [string]$DatabaseAdminUsername,
    [Parameter(Mandatory = $true)]
    [string]$DatabaseAdminPassword
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not installed or not on PATH."
    }
}

function Require-NonEmpty {
    param(
        [string]$Name,
        [string]$Value
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Resolved value for '$Name' is empty. Check your Azure resources and input parameters."
    }
}

function Set-GhVariable {
    param(
        [string]$Name,
        [string]$Value,
        [string]$EnvName
    )
    Require-NonEmpty -Name $Name -Value $Value
    gh variable set $Name --env $EnvName --body $Value | Out-Null
    Write-Host "Set variable: $Name"
}

function Set-GhSecret {
    param(
        [string]$Name,
        [string]$Value,
        [string]$EnvName
    )
    Require-NonEmpty -Name $Name -Value $Value
    $Value | gh secret set $Name --env $EnvName | Out-Null
    Write-Host "Set secret: $Name"
}

Require-Command -Name "az"
Require-Command -Name "gh"

$null = az account show | Out-Null
$null = gh auth status | Out-Null

Write-Host "Resolving Azure values..."

$docIntelEndpoint = az cognitiveservices account show `
    --resource-group $DocIntelResourceGroup `
    --name $DocIntelAccountName `
    --query properties.endpoint -o tsv

$openAiSubdomain = az cognitiveservices account show `
    --resource-group $OpenAIResourceGroup `
    --name $OpenAIAccountName `
    --query properties.customSubDomainName -o tsv

if ([string]::IsNullOrWhiteSpace($openAiSubdomain)) {
    $openAiEndpoint = az cognitiveservices account show `
        --resource-group $OpenAIResourceGroup `
        --name $OpenAIAccountName `
        --query properties.endpoint -o tsv
} else {
    $openAiEndpoint = "https://$openAiSubdomain.openai.azure.com/"
}

$searchApiKey = az search admin-key show `
    --resource-group $SearchResourceGroup `
    --service-name $SearchServiceName `
    --query primaryKey -o tsv

$storageConnectionString = az storage account show-connection-string `
    --resource-group $StorageResourceGroup `
    --name $StorageAccountName `
    --query connectionString -o tsv

$docIntelApiKey = az cognitiveservices account keys list `
    --resource-group $DocIntelResourceGroup `
    --name $DocIntelAccountName `
    --query key1 -o tsv

$openAiApiKey = az cognitiveservices account keys list `
    --resource-group $OpenAIResourceGroup `
    --name $OpenAIAccountName `
    --query key1 -o tsv

Write-Host "Applying GitHub environment config for '$EnvironmentName'..."

# Variables used by deploy-container-apps.yml
Set-GhVariable -Name "AZURE_RESOURCE_GROUP" -Value $AzureResourceGroup -EnvName $EnvironmentName
Set-GhVariable -Name "SEARCH_SERVICE_NAME" -Value $SearchServiceName -EnvName $EnvironmentName
Set-GhVariable -Name "SEARCH_INDEX_NAME" -Value $SearchIndexName -EnvName $EnvironmentName
Set-GhVariable -Name "STORAGE_ACCOUNT_NAME" -Value $StorageAccountName -EnvName $EnvironmentName
Set-GhVariable -Name "STORAGE_CONTAINER_NAME" -Value $StorageContainerName -EnvName $EnvironmentName
Set-GhVariable -Name "DOCUMENT_INTELLIGENCE_ENDPOINT" -Value $docIntelEndpoint -EnvName $EnvironmentName
Set-GhVariable -Name "OPENAI_ENDPOINT" -Value $openAiEndpoint -EnvName $EnvironmentName
Set-GhVariable -Name "OPENAI_DEPLOYMENT_NAME" -Value $OpenAIDeploymentName -EnvName $EnvironmentName
Set-GhVariable -Name "OPENAI_API_VERSION" -Value $OpenAIApiVersion -EnvName $EnvironmentName
Set-GhVariable -Name "DATABASE_ADMIN_USERNAME" -Value $DatabaseAdminUsername -EnvName $EnvironmentName

# Secrets used by deploy-container-apps.yml
Set-GhSecret -Name "DATABASE_ADMIN_PASSWORD" -Value $DatabaseAdminPassword -EnvName $EnvironmentName
Set-GhSecret -Name "SEARCH_API_KEY" -Value $searchApiKey -EnvName $EnvironmentName
Set-GhSecret -Name "STORAGE_CONNECTION_STRING" -Value $storageConnectionString -EnvName $EnvironmentName
Set-GhSecret -Name "DOCUMENT_INTELLIGENCE_API_KEY" -Value $docIntelApiKey -EnvName $EnvironmentName
Set-GhSecret -Name "OPENAI_API_KEY" -Value $openAiApiKey -EnvName $EnvironmentName

Write-Host "Done. GitHub environment '$EnvironmentName' now has all required deploy values."
Write-Host "Next: gh workflow run 'Deploy Azure Container Apps' --ref main -f environment=$EnvironmentName"