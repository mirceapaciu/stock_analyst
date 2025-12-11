#!/bin/bash

# Script to create AWS Lightsail Container Service
# This script recreates the container service as it currently exists

set -e  # Exit on error

# Configuration variables
SERVICE_NAME="stock-analysis"
REGION="eu-central-1"
POWER="small"
SCALE=1
DEPLOYMENT_JSON="lightsail-deployment.json"

echo "Creating AWS Lightsail Container Service: $SERVICE_NAME"
echo "Region: $REGION"
echo "Power: $POWER"
echo "Scale: $SCALE"
echo ""

# Check if service already exists
if aws lightsail get-container-service --service-name "$SERVICE_NAME" --region "$REGION" &>/dev/null; then
    echo "Warning: Container service '$SERVICE_NAME' already exists!"
    read -p "Do you want to continue? This will create a new deployment. (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_JSON_PATH="$SCRIPT_DIR/$DEPLOYMENT_JSON"

# Check if deployment JSON file exists
if [ ! -f "$DEPLOYMENT_JSON_PATH" ]; then
    echo "Error: Deployment JSON file not found: $DEPLOYMENT_JSON_PATH"
    exit 1
fi

# Create container service if it doesn't exist
if ! aws lightsail get-container-service --service-name "$SERVICE_NAME" --region "$REGION" &>/dev/null; then
    echo "Creating container service..."
    aws lightsail create-container-service \
        --service-name "$SERVICE_NAME" \
        --power "$POWER" \
        --scale "$SCALE" \
        --region "$REGION"
    
    echo "Waiting for container service to be ready..."
    aws lightsail wait container-service-ready \
        --service-name "$SERVICE_NAME" \
        --region "$REGION"
    
    echo "Container service created successfully!"
else
    echo "Container service already exists. Updating configuration..."
    aws lightsail update-container-service \
        --service-name "$SERVICE_NAME" \
        --power "$POWER" \
        --scale "$SCALE" \
        --region "$REGION"
fi

# Deploy the container using the JSON file
echo ""
echo "Deploying container from $DEPLOYMENT_JSON..."
aws lightsail create-container-service-deployment \
    --service-name "$SERVICE_NAME" \
    --cli-input-json "file://$DEPLOYMENT_JSON_PATH" \
    --region "$REGION"

echo ""
echo "Deployment initiated successfully!"
echo ""
echo "To check deployment status, run:"
echo "  aws lightsail get-container-service --service-name $SERVICE_NAME --region $REGION"
echo ""
echo "To view logs, run:"
echo "  aws lightsail get-container-log --service-name $SERVICE_NAME --container-name stock-analysis --region $REGION"

