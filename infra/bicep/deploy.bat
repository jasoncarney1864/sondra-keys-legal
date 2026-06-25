@echo off
REM Deployment script for Sondra Keys Legal QA infrastructure (Windows)
REM Usage: deploy.bat [environment] [location]

setlocal enabledelayedexpansion

set ENVIRONMENT=%1
if "!ENVIRONMENT!"=="" set ENVIRONMENT=dev

set LOCATION=%2
if "!LOCATION!"=="" set LOCATION=eastus

set RESOURCE_GROUP=rg-sondra-keys-legal-!ENVIRONMENT!
set APP_NAME=sondra-keys

echo.
echo ======================================================================
echo Deploying Sondra Keys Legal QA Infrastructure
echo ======================================================================
echo Environment: !ENVIRONMENT!
echo Location: !LOCATION!
echo Resource Group: !RESOURCE_GROUP!
echo.

REM Check if Azure CLI is installed
where az >nul 2>nul
if errorlevel 1 (
    echo Error: Azure CLI is not installed. Please install it first.
    exit /b 1
)

REM Login to Azure
echo Logging into Azure...
call az login

REM Get current subscription
for /f "delims=" %%i in ('az account show --query id -o tsv') do set SUBSCRIPTION_ID=%%i
echo Using subscription: !SUBSCRIPTION_ID!

REM Create resource group
echo.
echo Creating resource group: !RESOURCE_GROUP!
call az group create ^
    --name "!RESOURCE_GROUP!" ^
    --location "!LOCATION!" ^
    --tags environment="!ENVIRONMENT!" app="!APP_NAME!"

REM Deploy infrastructure
echo.
echo Deploying infrastructure...
for /f "delims=" %%i in ('powershell -Command "Get-Date -UFormat %%s"') do set TIMESTAMP=%%i
set DEPLOYMENT_NAME=!APP_NAME!-!ENVIRONMENT!-!TIMESTAMP!

call az deployment group create ^
    --name "!DEPLOYMENT_NAME!" ^
    --resource-group "!RESOURCE_GROUP!" ^
    --template-file main.bicep ^
    --parameters ^
        location="!LOCATION!" ^
        environment="!ENVIRONMENT!" ^
        appName="!APP_NAME!"

REM Get deployment outputs
echo.
echo ======================================================================
echo Deployment Complete!
echo ======================================================================

call az deployment group show ^
    --name "!DEPLOYMENT_NAME!" ^
    --resource-group "!RESOURCE_GROUP!" ^
    --query "properties.outputs" ^
    -o json

echo.
echo Next steps:
echo 1. Configure GitHub Secrets with values from outputs above
echo 2. Push Docker image to Container Registry
echo 3. Configure Static Web App GitHub integration
echo.
