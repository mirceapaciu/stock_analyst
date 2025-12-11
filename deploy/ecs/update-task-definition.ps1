# PowerShell script to update task definition with EFS ID and account ID

param(
    [Parameter(Mandatory=$true)]
    [string]$EfsId,
    
    [Parameter(Mandatory=$true)]
    [string]$AccountId,
    
    [string]$TaskDefFile = "task-definition.json"
)

$ErrorActionPreference = "Stop"

Write-Host "Updating task definition..." -ForegroundColor Green
Write-Host "EFS ID: $EfsId" -ForegroundColor Yellow
Write-Host "Account ID: $AccountId" -ForegroundColor Yellow

if (-not (Test-Path $TaskDefFile)) {
    Write-Host "Error: Task definition file not found: $TaskDefFile" -ForegroundColor Red
    exit 1
}

# Read file content
$content = Get-Content $TaskDefFile -Raw

# Replace placeholders
$content = $content -replace "EFS_FILE_SYSTEM_ID", $EfsId
$content = $content -replace "ACCOUNT_ID", $AccountId

# Write back to file
Set-Content -Path $TaskDefFile -Value $content -NoNewline

Write-Host "Task definition updated successfully!" -ForegroundColor Green
Write-Host "Review $TaskDefFile before registering" -ForegroundColor Yellow

