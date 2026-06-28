#!/usr/bin/env pwsh
#Requires -Version 7.0

<#
.SYNOPSIS
    Deploy Sondra Keys Legal application to Azure Container Apps

.DESCRIPTION
    Builds Docker images, pushes to ACR, and deploys infrastructure using Bicep

.PARAMETER Environment
    Target environment (dev, staging, prod)

.PARAMETER ImageTag
    Docker image tag to use (default: latest)

.PARAMETER SkipBuild
    Skip Docker image build and push

.PARAMETER DatabasePassword
    Database administrator password (required if not using Key Vault)

.PARAMETER SearchApiKey
    Azure Cognitive Search API key (required if not using Key Vault)

.PARAMETER StorageConnectionString
    Azure Blob Storage connection string (required if not using Key Vault)

.PARAMETER DocumentIntelligenceApiKey
    Azure Document Intelligence API key (required if not using Key Vault)

.PARAMETER OpenAIApiKey
    Azure OpenAI/Foundry API key (required if not using Key Vault)

.EXAMPLE
    .\deploy.ps1 -Environment dev

.EXAMPLE
    .\deploy.ps1 -Environment dev -ImageTag v1.2.0

.EXAMPLE
    .\deploy.ps1 -Environment dev -DatabasePassword "Pass123!" -SearchApiKey "key" -StorageConnectionString "conn" -DocumentIntelligenceApiKey "key" -OpenAIApiKey "key"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('dev', 'staging', 'prod')]
    [string]$Environment,

    [Parameter(Mandatory=$false)]
    [string]$ImageTag = 'latest',

    [Parameter(Mandatory=$false)]
    [switch]$SkipBuild,

    [Parameter(Mandatory=$false)]
    [string]$DatabasePassword,

    [Parameter(Mandatory=$false)]
    [string]$SearchApiKey,

    [Parameter(Mandatory=$false)]
    [string]$StorageConnectionString,

    [Parameter(Mandatory=$false)]
    [string]$DocumentIntelligenceApiKey,

    [Parameter(Mandatory=$false)]
    [string]$OpenAIApiKey
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Configuration
$ResourceGroupName = "rg-sondra-legal-$Environment"
$Location = "eastus"
$ACRName = "acrsondralegal$Environment"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Sondra Keys Legal Deployment ===" -ForegroundColor Cyan
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host "Image Tag: $ImageTag" -ForegroundColor Yellow
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Yellow

# Check Azure CLI
Write-Host "`n[1/5] Checking Azure CLI..." -ForegroundColor Cyan
try {
    $null = az account show 2>&1
    $accountInfo = az account show | ConvertFrom-Json
    Write-Host "✓ Logged in as: $($accountInfo.user.name)" -ForegroundColor Green
} catch {
    Write-Error "Azure CLI not authenticated. Run: az login"
}

# Check Docker
if (-not $SkipBuild) {
    Write-Host "`n[2/5] Checking Docker..." -ForegroundColor Cyan
    try {
        $null = docker version 2>&1
        Write-Host "✓ Docker is running" -ForegroundColor Green
    } catch {
        Write-Error "Docker is not running. Please start Docker Desktop."
    }
}

# Build and push images
if (-not $SkipBuild) {
    Write-Host "`n[3/5] Building and pushing Docker images..." -ForegroundColor Cyan
    
    # Deploy infrastructure first to create ACR (if not exists)
    Write-Host "  → Ensuring ACR exists..." -ForegroundColor Yellow
    az deployment sub create `
        --location $Location `
        --template-file "$PSScriptRoot/main.bicep" `
        --parameters "$PSScriptRoot/main.parameters.json" `
        --parameters environment=$Environment `
        --parameters imageTag=placeholder `
        --name "acr-bootstrap-$(Get-Date -Format 'yyyyMMddHHmmss')" `
        --only-show-errors | Out-Null
    
    # Login to ACR
    Write-Host "  → Logging in to ACR..." -ForegroundColor Yellow
    az acr login --name $ACRName
    
    # Build and push backend
    Write-Host "  → Building backend image..." -ForegroundColor Yellow
    docker build `
        -t "$ACRName.azurecr.io/sondra-legal-backend:$ImageTag" `
        -t "$ACRName.azurecr.io/sondra-legal-backend:latest" `
        -f "$ProjectRoot/backend/Dockerfile" `
        "$ProjectRoot"
    
    Write-Host "  → Pushing backend image..." -ForegroundColor Yellow
    docker push "$ACRName.azurecr.io/sondra-legal-backend:$ImageTag"
    docker push "$ACRName.azurecr.io/sondra-legal-backend:latest"
    
    # Build and push frontend
    Write-Host "  → Building frontend image..." -ForegroundColor Yellow
    docker build `
        -t "$ACRName.azurecr.io/sondra-legal-frontend:$ImageTag" `
        -t "$ACRName.azurecr.io/sondra-legal-frontend:latest" `
        -f "$ProjectRoot/frontend/Dockerfile" `
        "$ProjectRoot/frontend"
    
    Write-Host "  → Pushing frontend image..." -ForegroundColor Yellow
    docker push "$ACRName.azurecr.io/sondra-legal-frontend:$ImageTag"
    docker push "$ACRName.azurecr.io/sondra-legal-frontend:latest"
    
    Write-Host "✓ Images built and pushed" -ForegroundColor Green
} else {
    Write-Host "`n[3/5] Skipping image build (--SkipBuild)" -ForegroundColor Yellow
}

# Prepare deployment parameters
Write-Host "`n[4/5] Preparing deployment..." -ForegroundColor Cyan

$DeploymentParams = @(
    "environment=$Environment",
    "imageTag=$ImageTag"
)

# Add secrets if provided directly
if ($DatabasePassword) {
    $DeploymentParams += "databaseAdminPassword=$DatabasePassword"
}
if ($SearchApiKey) {
    $DeploymentParams += "searchApiKey=$SearchApiKey"
}
if ($StorageConnectionString) {
    $DeploymentParams += "storageConnectionString=$StorageConnectionString"
}
if ($DocumentIntelligenceApiKey) {
    $DeploymentParams += "documentIntelligenceApiKey=$DocumentIntelligenceApiKey"
}
if ($OpenAIApiKey) {
    $DeploymentParams += "openAIApiKey=$OpenAIApiKey"
}

# Deploy infrastructure
Write-Host "`n[5/5] Deploying infrastructure..." -ForegroundColor Cyan
$DeploymentName = "sondra-legal-$Environment-$(Get-Date -Format 'yyyyMMddHHmmss')"

$DeploymentResult = az deployment sub create `
    --location $Location `
    --template-file "$PSScriptRoot/main.bicep" `
    --parameters "$PSScriptRoot/main.parameters.json" `
    --parameters $DeploymentParams `
    --name $DeploymentName `
    --output json | ConvertFrom-Json

if ($LASTEXITCODE -ne 0) {
    Write-Error "Deployment failed. Check error messages above."
}

Write-Host "✓ Deployment completed successfully" -ForegroundColor Green

# Output results
Write-Host "`n=== Deployment Complete ===" -ForegroundColor Cyan
Write-Host "Frontend URL: $($DeploymentResult.properties.outputs.frontendUrl.value)" -ForegroundColor Green
Write-Host "Backend URL:  $($DeploymentResult.properties.outputs.backendUrl.value)" -ForegroundColor Green
Write-Host "Database:     $($DeploymentResult.properties.outputs.databaseHost.value)" -ForegroundColor Green

Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "1. Run database migrations (if needed)" -ForegroundColor White
Write-Host "2. Test the application at the frontend URL" -ForegroundColor White
Write-Host "3. Monitor logs in Azure Portal or CLI" -ForegroundColor White
