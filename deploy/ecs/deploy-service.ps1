# PowerShell script to deploy ECS service with Fargate

param(
    [string]$ClusterName = "stock-analysis-cluster",
    [string]$ServiceName = "stock-analysis-service",
    [string]$TaskDefinition = "stock-analysis-app",
    [string]$Region = "eu-central-1",
    [int]$DesiredCount = 1
)

$ErrorActionPreference = "Stop"

Write-Host "Deploying ECS service..." -ForegroundColor Green
Write-Host "Cluster: $ClusterName" -ForegroundColor Yellow
Write-Host "Service: $ServiceName" -ForegroundColor Yellow

# Get VPC and subnet configuration
$VpcId = aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text --region $Region
$SubnetIds = aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VpcId" --query "Subnets[*].SubnetId" --output text --region $Region
$SubnetIdsArray = $SubnetIds -split "`t" | ForEach-Object { "'$_'" }
$SubnetIdsString = $SubnetIdsArray -join ","

# Get security group (use default or create one)
$SgId = aws ec2 describe-security-groups --filters "Name=group-name,Values=default" "Name=vpc-id,Values=$VpcId" --query "SecurityGroups[0].GroupId" --output text --region $Region

Write-Host "VPC: $VpcId" -ForegroundColor Yellow
Write-Host "Subnets: $SubnetIdsString" -ForegroundColor Yellow
Write-Host "Security Group: $SgId" -ForegroundColor Yellow

# Check if service already exists
try {
    $existingService = aws ecs describe-services --cluster $ClusterName --services $ServiceName --region $Region --query "services[0].serviceName" --output text 2>$null
    if ($existingService -eq $ServiceName) {
        Write-Host "Service already exists. Updating..." -ForegroundColor Yellow
        aws ecs update-service `
            --cluster $ClusterName `
            --service $ServiceName `
            --task-definition $TaskDefinition `
            --desired-count $DesiredCount `
            --region $Region `
            --force-new-deployment
        
        Write-Host "Service updated. Waiting for deployment to stabilize..." -ForegroundColor Yellow
        aws ecs wait services-stable --cluster $ClusterName --services $ServiceName --region $Region
    }
} catch {
    Write-Host "Creating new service..." -ForegroundColor Yellow
    $networkConfig = "awsvpcConfiguration={subnets=[$SubnetIdsString],securityGroups=['$SgId'],assignPublicIp=ENABLED}"
    
    aws ecs create-service `
        --cluster $ClusterName `
        --service-name $ServiceName `
        --task-definition $TaskDefinition `
        --desired-count $DesiredCount `
        --launch-type FARGATE `
        --network-configuration $networkConfig `
        --region $Region `
        --health-check-grace-period-seconds 60
    
    Write-Host "Service created. Waiting for service to be stable..." -ForegroundColor Yellow
    aws ecs wait services-stable --cluster $ClusterName --services $ServiceName --region $Region
}

# Get service details and ensure security group allows port 8080
Write-Host "Configuring security group for port 8080..." -ForegroundColor Yellow
$ServiceJson = aws ecs describe-services --cluster $ClusterName --services $ServiceName --region $Region --query "services[0]" | ConvertFrom-Json
$ServiceArn = $ServiceJson.serviceArn

# Get the actual security group ID from the service (in case it changed)
$ServiceSgId = $ServiceJson.networkConfiguration.awsvpcConfiguration.securityGroups[0]
if (-not $ServiceSgId) {
    $ServiceSgId = $SgId
}

# Check if port 8080 rule exists
$CurrentRules = aws ec2 describe-security-groups --group-ids $ServiceSgId --region $Region --query "SecurityGroups[0].IpPermissions" | ConvertFrom-Json
$HasPort8080 = $false
foreach ($rule in $CurrentRules) {
    if ($rule.FromPort -eq 8080 -and $rule.ToPort -eq 8080 -and $rule.IpProtocol -eq "tcp") {
        $HasPort8080 = $true
        # Check if it allows public access
        $AllowsPublic = $false
        foreach ($ipRange in $rule.IpRanges) {
            if ($ipRange.CidrIp -eq "0.0.0.0/0") {
                $AllowsPublic = $true
                break
            }
        }
        if (-not $AllowsPublic) {
            $HasPort8080 = $false
        }
        break
    }
}

if (-not $HasPort8080) {
    Write-Host "Adding inbound rule for port 8080 from 0.0.0.0/0..." -ForegroundColor Yellow
    try {
        aws ec2 authorize-security-group-ingress `
            --group-id $ServiceSgId `
            --protocol tcp `
            --port 8080 `
            --cidr 0.0.0.0/0 `
            --region $Region | Out-Null
        Write-Host "Security group rule added successfully." -ForegroundColor Green
    } catch {
        Write-Host "Note: Rule may already exist or error occurred: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "Security group already allows port 8080." -ForegroundColor Green
}

$TaskArn = aws ecs list-tasks --cluster $ClusterName --service-name $ServiceName --region $Region --query "taskArns[0]" --output text

if (-not [string]::IsNullOrEmpty($TaskArn) -and $TaskArn -ne "None") {
    # Get network interface ID
    $NetworkInterfaceId = aws ecs describe-tasks --cluster $ClusterName --tasks $TaskArn --region $Region --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text
    
    if (-not [string]::IsNullOrEmpty($NetworkInterfaceId)) {
        $PublicIp = aws ec2 describe-network-interfaces --network-interface-ids $NetworkInterfaceId --region $Region --query "NetworkInterfaces[0].Association.PublicIp" --output text
        
        Write-Host ""
        Write-Host "==========================================" -ForegroundColor Green
        Write-Host "Deployment Complete!" -ForegroundColor Green
        Write-Host "==========================================" -ForegroundColor Green
        Write-Host "Service ARN: $ServiceArn" -ForegroundColor Green
        Write-Host "Public IP: $PublicIp" -ForegroundColor Green
        Write-Host "Access your app at: http://$PublicIp:8080" -ForegroundColor Green
        Write-Host ""
    }
} else {
    Write-Host ""
    Write-Host "Service deployed. Check AWS Console for task details." -ForegroundColor Yellow
    Write-Host ""
}

