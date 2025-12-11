# PowerShell script to create EFS file system for persistent storage

param(
    [string]$Region = "eu-central-1",
    [string]$EfsName = "stock-analysis-efs",
    [string]$VpcId = "",
    [string[]]$SubnetIds = @()
)

$ErrorActionPreference = "Stop"

Write-Host "Creating EFS file system for stock analysis app..." -ForegroundColor Green

# Get default VPC if not set
if ([string]::IsNullOrEmpty($VpcId)) {
    Write-Host "Detecting default VPC..." -ForegroundColor Yellow
    $vpcs = aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text --region $Region
    if ($vpcs -eq "None" -or [string]::IsNullOrEmpty($vpcs)) {
        Write-Host "No default VPC found. Please set VpcId manually." -ForegroundColor Red
        exit 1
    }
    $VpcId = $vpcs
    Write-Host "Using VPC: $VpcId" -ForegroundColor Green
}

# Get subnets in the VPC if not provided
if ($SubnetIds.Count -eq 0) {
    Write-Host "Detecting subnets in VPC..." -ForegroundColor Yellow
    $subnets = aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VpcId" --query "Subnets[*].SubnetId" --output text --region $Region
    if ([string]::IsNullOrEmpty($subnets)) {
        Write-Host "No subnets found in VPC. Please set SubnetIds manually." -ForegroundColor Red
        exit 1
    }
    $SubnetIds = $subnets -split "`t"
    Write-Host "Using subnets: $($SubnetIds -join ', ')" -ForegroundColor Green
}

# Check if EFS already exists
$existingEfs = aws efs describe-file-systems --region $Region --query "FileSystems[?Name=='$EfsName'].FileSystemId" --output text

if (-not [string]::IsNullOrEmpty($existingEfs)) {
    Write-Host "EFS file system already exists: $existingEfs" -ForegroundColor Yellow
    $EfsId = $existingEfs
} else {
    # Create EFS file system
    Write-Host "Creating EFS file system..." -ForegroundColor Yellow
    $EfsId = aws efs create-file-system `
        --region $Region `
        --performance-mode generalPurpose `
        --throughput-mode provisioned `
        --provisioned-throughput-in-mibps 100 `
        --encrypted `
        --tags "Key=Name,Value=$EfsName" `
        --query "FileSystemId" `
        --output text
    
    Write-Host "Created EFS: $EfsId" -ForegroundColor Green
    
    # Wait for EFS to be available
    Write-Host "Waiting for EFS to be available..." -ForegroundColor Yellow
    aws efs wait file-system-available --file-system-id $EfsId --region $Region
}

# Get security group for EFS (create if doesn't exist)
$SgName = "efs-sg-$EfsName"
$sgResult = aws ec2 describe-security-groups `
    --filters "Name=group-name,Values=$SgName" "Name=vpc-id,Values=$VpcId" `
    --query "SecurityGroups[0].GroupId" `
    --output text `
    --region $Region

if ($sgResult -eq "None" -or [string]::IsNullOrEmpty($sgResult)) {
    Write-Host "Creating security group for EFS..." -ForegroundColor Yellow
    $SgId = aws ec2 create-security-group `
        --group-name $SgName `
        --description "Security group for EFS access" `
        --vpc-id $VpcId `
        --query "GroupId" `
        --output text `
        --region $Region
    
    # Get VPC CIDR
    $vpcCidr = aws ec2 describe-vpcs --vpc-ids $VpcId --query "Vpcs[0].CidrBlock" --output text --region $Region
    
    # Allow NFS traffic from VPC
    aws ec2 authorize-security-group-ingress `
        --group-id $SgId `
        --protocol tcp `
        --port 2049 `
        --cidr $vpcCidr `
        --region $Region
    
    Write-Host "Created security group: $SgId" -ForegroundColor Green
} else {
    $SgId = $sgResult
    Write-Host "Using existing security group: $SgId" -ForegroundColor Green
}

# Create mount targets for each subnet
Write-Host "Creating mount targets..." -ForegroundColor Yellow
foreach ($SubnetId in $SubnetIds) {
    # Check if mount target already exists
    $existingMt = aws efs describe-mount-targets `
        --file-system-id $EfsId `
        --region $Region `
        --query "MountTargets[?SubnetId=='$SubnetId'].MountTargetId" `
        --output text
    
    if ([string]::IsNullOrEmpty($existingMt) -or $existingMt -eq "None") {
        Write-Host "Creating mount target for subnet: $SubnetId" -ForegroundColor Yellow
        aws efs create-mount-target `
            --file-system-id $EfsId `
            --subnet-id $SubnetId `
            --security-groups $SgId `
            --region $Region
        
        Write-Host "Created mount target for subnet: $SubnetId" -ForegroundColor Green
    } else {
        Write-Host "Mount target already exists for subnet: $SubnetId" -ForegroundColor Yellow
    }
}

# Wait for mount targets to be available
Write-Host "Waiting for mount targets to be available..." -ForegroundColor Yellow
foreach ($SubnetId in $SubnetIds) {
    $mtId = aws efs describe-mount-targets `
        --file-system-id $EfsId `
        --region $Region `
        --query "MountTargets[?SubnetId=='$SubnetId'].MountTargetId" `
        --output text
    
    if (-not [string]::IsNullOrEmpty($mtId) -and $mtId -ne "None") {
        aws efs wait mount-target-available --mount-target-id $mtId --region $Region
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "EFS Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "EFS ID: $EfsId" -ForegroundColor Green
Write-Host "Security Group: $SgId" -ForegroundColor Green
Write-Host "Region: $Region" -ForegroundColor Green
Write-Host ""
Write-Host "Save these values for the ECS task definition:"
Write-Host "  EFS_ID=$EfsId"
Write-Host "  EFS_SG_ID=$SgId"
Write-Host ""
Write-Host "EFS DNS name: $EfsId.efs.$Region.amazonaws.com"
Write-Host ""

