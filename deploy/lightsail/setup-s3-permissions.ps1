# Script to attach S3 permissions to Lightsail container service
# This grants the container service IAM role access to the S3 bucket

$SERVICE_NAME = "stock-analysis"
$REGION = "eu-central-1"
$BUCKET_NAME = "stock-analysis-data-3666"
$POLICY_NAME = "LightsailContainerServiceS3Access"

Write-Host "Setting up S3 permissions for Lightsail container service" -ForegroundColor Cyan
Write-Host "Service: $SERVICE_NAME" -ForegroundColor Gray
Write-Host "Bucket: $BUCKET_NAME" -ForegroundColor Gray
Write-Host ""

# Get the directory where this script is located
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$POLICY_JSON_PATH = Join-Path (Split-Path -Parent $SCRIPT_DIR) "s3-policy.json"

# Check if policy JSON file exists
if (-not (Test-Path $POLICY_JSON_PATH)) {
    Write-Host "Error: S3 policy file not found: $POLICY_JSON_PATH" -ForegroundColor Red
    exit 1
}

# Get the container service principal ARN (IAM role)
Write-Host "Fetching container service IAM role..." -ForegroundColor Yellow
$service = aws lightsail get-container-services --region $REGION | ConvertFrom-Json
$containerService = $service.containerServices | Where-Object { $_.containerServiceName -eq $SERVICE_NAME }

if (-not $containerService) {
    Write-Host "Error: Container service '$SERVICE_NAME' not found!" -ForegroundColor Red
    exit 1
}

$ROLE_ARN = $containerService.principalArn
Write-Host "Container service role: $ROLE_ARN" -ForegroundColor Gray

# Extract the role name from the ARN
# Format: arn:aws:iam::ACCOUNT:role/amazon/lightsail/REGION/containers/SERVICE/ROLE_ID
# The role name is everything after /role/
$ROLE_NAME = $ROLE_ARN -replace '^arn:aws:iam::[^:]+:role/', ''
$ACCOUNT_ID = ($ROLE_ARN -split ':')[4]

Write-Host "Role name: $ROLE_NAME" -ForegroundColor Gray
Write-Host "Account ID: $ACCOUNT_ID" -ForegroundColor Gray
Write-Host ""

# Check if policy already exists
Write-Host "Checking if policy '$POLICY_NAME' already exists..." -ForegroundColor Yellow
$POLICY_ARN = "arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
$existingPolicy = aws iam get-policy --policy-arn $POLICY_ARN 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "Policy already exists. Updating policy version..." -ForegroundColor Yellow
    
    # Create new policy version
    $policyVersion = aws iam create-policy-version `
        --policy-arn $POLICY_ARN `
        --policy-document "file://$POLICY_JSON_PATH" `
        --set-as-default | ConvertFrom-Json
    
    Write-Host "Policy version created: $($policyVersion.PolicyVersion.VersionId)" -ForegroundColor Green
    
    # List old versions and delete non-default ones (keep last 4)
    $versions = aws iam list-policy-versions --policy-arn $POLICY_ARN | ConvertFrom-Json
    $nonDefaultVersions = $versions.Versions | Where-Object { -not $_.IsDefaultVersion } | Sort-Object CreateDate -Descending | Select-Object -Skip 4
    
    foreach ($version in $nonDefaultVersions) {
        Write-Host "Deleting old policy version: $($version.VersionId)" -ForegroundColor Gray
        aws iam delete-policy-version `
            --policy-arn $POLICY_ARN `
            --version-id $version.VersionId | Out-Null
    }
} else {
    Write-Host "Creating new IAM policy: $POLICY_NAME" -ForegroundColor Yellow
    $newPolicy = aws iam create-policy `
        --policy-name $POLICY_NAME `
        --policy-document "file://$POLICY_JSON_PATH" `
        --description "Allows Lightsail container service to access S3 bucket for database persistence" | ConvertFrom-Json
    
    Write-Host "Policy created: $($newPolicy.Policy.Arn)" -ForegroundColor Green
}

# Check if policy is already attached to the role
Write-Host ""
Write-Host "Checking if policy is attached to role..." -ForegroundColor Yellow
$attachedPolicies = aws iam list-attached-role-policies --role-name $ROLE_NAME | ConvertFrom-Json

$isAttached = $attachedPolicies.AttachedPolicies | Where-Object { $_.PolicyArn -eq $POLICY_ARN }

if ($isAttached) {
    Write-Host "Policy is already attached to the role." -ForegroundColor Green
} else {
    Write-Host "Attaching policy to role: $ROLE_NAME" -ForegroundColor Yellow
    
    try {
        aws iam attach-role-policy `
            --role-name $ROLE_NAME `
            --policy-arn $POLICY_ARN
        
        Write-Host "Policy attached successfully!" -ForegroundColor Green
    } catch {
        Write-Host "Error attaching policy: $_" -ForegroundColor Red
        Write-Host ""
        Write-Host "You may need to attach the policy manually:" -ForegroundColor Yellow
        Write-Host "  aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn $POLICY_ARN" -ForegroundColor White
        exit 1
    }
}

Write-Host ""
Write-Host "S3 permissions setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "The container service now has access to:" -ForegroundColor Cyan
Write-Host "  - s3:GetObject (download files)" -ForegroundColor White
Write-Host "  - s3:PutObject (upload files)" -ForegroundColor White
Write-Host "  - s3:HeadObject (check if files exist)" -ForegroundColor White
Write-Host "  - s3:DeleteObject (delete files)" -ForegroundColor White
Write-Host "  - s3:ListBucket (list bucket contents)" -ForegroundColor White
Write-Host ""
Write-Host "Bucket: $BUCKET_NAME" -ForegroundColor Gray
Write-Host ""
Write-Host "Note: It may take a few minutes for the permissions to propagate." -ForegroundColor Yellow
Write-Host "If you still see access denied errors, wait a few minutes and try again." -ForegroundColor Yellow

