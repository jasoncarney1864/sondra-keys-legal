#!/bin/bash

# Deployment script for Sondra Keys Legal QA infrastructure
# Usage: ./deploy.sh [environment] [location]

set -e

ENVIRONMENT=${1:-dev}
LOCATION=${2:-eastus}
RESOURCE_GROUP="rg-sondra-keys-legal-${ENVIRONMENT}"
APP_NAME="sondra-keys"

echo "======================================================================"
echo "Deploying Sondra Keys Legal QA Infrastructure"
echo "======================================================================"
echo "Environment: $ENVIRONMENT"
echo "Location: $LOCATION"
echo "Resource Group: $RESOURCE_GROUP"
echo ""

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo "Error: Azure CLI is not installed. Please install it first."
    exit 1
fi

# Login to Azure
echo "Logging into Azure..."
az login

# Get current subscription
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "Using subscription: $SUBSCRIPTION_ID"

# Create resource group
echo ""
echo "Creating resource group: $RESOURCE_GROUP"
az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --tags environment="$ENVIRONMENT" app="$APP_NAME"

# Deploy infrastructure
echo ""
echo "Deploying infrastructure..."
DEPLOYMENT_NAME="${APP_NAME}-${ENVIRONMENT}-$(date +%s)"

az deployment group create \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --template-file main.bicep \
    --parameters \
        location="$LOCATION" \
        environment="$ENVIRONMENT" \
        appName="$APP_NAME"

# Get deployment outputs
echo ""
echo "======================================================================"
echo "Deployment Complete!"
echo "======================================================================"

az deployment group show \
    --name "$DEPLOYMENT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "properties.outputs" \
    -o json

echo ""
echo "Next steps:"
echo "1. Configure GitHub Secrets with values from outputs above"
echo "2. Push Docker image to Container Registry"
echo "3. Configure Static Web App GitHub integration"
echo ""
