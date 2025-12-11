# Script to create AWS Lightsail Container Service
# This script recreates the container service as it currently exists

# Configuration variables
$SERVICE_NAME = "stock-analysis"
$REGION = "eu-central-1"
$POWER = "small"
$SCALE = 1
$DEPLOYMENT_JSON = "lightsail-deployment.json"

Write-Host "Creating AWS Lightsail Container Service: $SERVICE_NAME" -ForegroundColor Cyan
Write-Host "Region: $REGION"
Write-Host "Power: $POWER"
Write-Host "Scale: $SCALE"
Write-Host ""

# Get the directory where this script is located
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$DEPLOYMENT_JSON_PATH = Join-Path $SCRIPT_DIR $DEPLOYMENT_JSON

# Check if deployment JSON file exists
if (-not (Test-Path $DEPLOYMENT_JSON_PATH)) {
    Write-Host "Error: Deployment JSON file not found: $DEPLOYMENT_JSON_PATH" -ForegroundColor Red
    exit 1
}

# Check if service already exists
try {
    $null = aws lightsail get-container-service --service-name $SERVICE_NAME --region $REGION 2>&1 | Out-Null
    $serviceExists = $true
} catch {
    $serviceExists = $false
}

if ($serviceExists) {
    Write-Host "Warning: Container service '$SERVICE_NAME' already exists!" -ForegroundColor Yellow
    $response = Read-Host "Do you want to continue? This will create a new deployment. (y/N)"
    if ($response -ne "y" -and $response -ne "Y") {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 1
    }
}

# Create container service if it doesn't exist
if (-not $serviceExists) {
    Write-Host "Creating container service..." -ForegroundColor Green
    aws lightsail create-container-service `
        --service-name $SERVICE_NAME `
        --power $POWER `
        --scale $SCALE `
        --region $REGION
    
    Write-Host "Waiting for container service to be ready..." -ForegroundColor Yellow
    $maxWaitTime = 300  # 5 minutes
    $elapsed = 0
    $interval = 10
    
    while ($elapsed -lt $maxWaitTime) {
        Start-Sleep -Seconds $interval
        $elapsed += $interval
        
        try {
            $service = aws lightsail get-container-service --service-name $SERVICE_NAME --region $REGION | ConvertFrom-Json
            if ($service.containerService.state -eq "RUNNING") {
                Write-Host "Container service is ready!" -ForegroundColor Green
                break
            }
        } catch {
            # Service might not be ready yet
        }
        
        Write-Host "Waiting... ($elapsed seconds)" -ForegroundColor Gray
    }
    
    Write-Host "Container service created successfully!" -ForegroundColor Green
} else {
    Write-Host "Container service already exists. Updating configuration..." -ForegroundColor Yellow
    aws lightsail update-container-service `
        --service-name $SERVICE_NAME `
        --power $POWER `
        --scale $SCALE `
        --region $REGION
}

# Deploy the container using the JSON file
Write-Host ""
Write-Host "Deploying container from $DEPLOYMENT_JSON..." -ForegroundColor Green
aws lightsail create-container-service-deployment `
    --service-name $SERVICE_NAME `
    --cli-input-json "file://$DEPLOYMENT_JSON_PATH" `
    --region $REGION

Write-Host ""
Write-Host "Deployment initiated successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "To check deployment status, run:" -ForegroundColor Cyan
Write-Host "  aws lightsail get-container-service --service-name $SERVICE_NAME --region $REGION"
Write-Host ""
Write-Host "To view logs, run:" -ForegroundColor Cyan
Write-Host "  aws lightsail get-container-log --service-name $SERVICE_NAME --container-name stock-analysis --region $REGION"

