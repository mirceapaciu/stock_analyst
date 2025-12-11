# PowerShell script to create ECS cluster for Fargate

param(
    [string]$ClusterName = "stock-analysis-cluster",
    [string]$Region = "eu-central-1"
)

$ErrorActionPreference = "Stop"

Write-Host "Creating ECS cluster: $ClusterName" -ForegroundColor Green

# Check if cluster already exists
try {
    $existingCluster = aws ecs describe-clusters --clusters $ClusterName --region $Region --query "clusters[0].clusterName" --output text 2>$null
    if ($existingCluster -eq $ClusterName) {
        Write-Host "Cluster already exists: $ClusterName" -ForegroundColor Yellow
    }
} catch {
    # Cluster doesn't exist, create it
    Write-Host "Creating cluster..." -ForegroundColor Yellow
    aws ecs create-cluster `
        --cluster-name $ClusterName `
        --region $Region `
        --capacity-providers FARGATE FARGATE_SPOT `
        --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1
    
    Write-Host "Created cluster: $ClusterName" -ForegroundColor Green
}

# Create CloudWatch log group
$LogGroup = "/ecs/stock-analysis-app"
try {
    $existingLogGroup = aws logs describe-log-groups --log-group-name-prefix $LogGroup --region $Region --query "logGroups[0].logGroupName" --output text 2>$null
    if ($existingLogGroup -eq $LogGroup) {
        Write-Host "Log group already exists: $LogGroup" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Creating log group..." -ForegroundColor Yellow
    aws logs create-log-group `
        --log-group-name $LogGroup `
        --region $Region
    Write-Host "Created log group: $LogGroup" -ForegroundColor Green
}

Write-Host ""
Write-Host "Cluster setup complete!" -ForegroundColor Green
Write-Host "Cluster name: $ClusterName" -ForegroundColor Green
Write-Host "Region: $Region" -ForegroundColor Green

