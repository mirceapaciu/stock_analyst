# Fix security group to allow inbound traffic on port 8080

$REGION = "eu-central-1"
$CLUSTER_NAME = "stock-analysis-cluster"
$SERVICE_NAME = "stock-analysis-service"

Write-Host "Checking ECS service configuration..." -ForegroundColor Cyan

# Get the service to find which security group it's using
$SERVICE = aws ecs describe-services `
    --cluster $CLUSTER_NAME `
    --services $SERVICE_NAME `
    --region $REGION `
    --query "services[0]" | ConvertFrom-Json

if (-not $SERVICE) {
    Write-Host "Error: Service not found!" -ForegroundColor Red
    exit 1
}

# Get security group ID from network configuration
$SECURITY_GROUPS = $SERVICE.networkConfiguration.awsvpcConfiguration.securityGroups

if ($SECURITY_GROUPS.Count -eq 0) {
    Write-Host "Error: No security groups found!" -ForegroundColor Red
    exit 1
}

$SG_ID = $SECURITY_GROUPS[0]
Write-Host "Service is using security group: $SG_ID" -ForegroundColor Yellow

# Check current inbound rules
Write-Host "`nChecking current security group rules..." -ForegroundColor Cyan
$CURRENT_RULES = aws ec2 describe-security-groups `
    --group-ids $SG_ID `
    --region $REGION `
    --query "SecurityGroups[0].IpPermissions" | ConvertFrom-Json

$HAS_PORT_8080 = $false
foreach ($rule in $CURRENT_RULES) {
    if ($rule.FromPort -eq 8080 -and $rule.ToPort -eq 8080 -and $rule.IpProtocol -eq "tcp") {
        $HAS_PORT_8080 = $true
        Write-Host "Found existing rule for port 8080" -ForegroundColor Green
        Write-Host "  Protocol: $($rule.IpProtocol)" -ForegroundColor Gray
        Write-Host "  Port: $($rule.FromPort)" -ForegroundColor Gray
        Write-Host "  Source IPs:" -ForegroundColor Gray
        foreach ($ipRange in $rule.IpRanges) {
            Write-Host "    - $($ipRange.CidrIp)" -ForegroundColor Gray
        }
        break
    }
}

if (-not $HAS_PORT_8080) {
    Write-Host "No rule found for port 8080. Adding inbound rule..." -ForegroundColor Yellow
    
    try {
        aws ec2 authorize-security-group-ingress `
            --group-id $SG_ID `
            --protocol tcp `
            --port 8080 `
            --cidr 0.0.0.0/0 `
            --region $REGION | Out-Null
        
        Write-Host "Successfully added inbound rule for port 8080 from 0.0.0.0/0" -ForegroundColor Green
    } catch {
        Write-Host "Error adding security group rule: $_" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "`nSecurity group already has port 8080 rule. Checking if it allows public access..." -ForegroundColor Yellow
    
    $ALLOWS_PUBLIC = $false
    foreach ($rule in $CURRENT_RULES) {
        if ($rule.FromPort -eq 8080 -and $rule.ToPort -eq 8080) {
            foreach ($ipRange in $rule.IpRanges) {
                if ($ipRange.CidrIp -eq "0.0.0.0/0") {
                    $ALLOWS_PUBLIC = $true
                    break
                }
            }
        }
    }
    
    if (-not $ALLOWS_PUBLIC) {
        Write-Host "Rule exists but doesn't allow public access (0.0.0.0/0). Adding public access rule..." -ForegroundColor Yellow
        try {
            aws ec2 authorize-security-group-ingress `
                --group-id $SG_ID `
                --protocol tcp `
                --port 8080 `
                --cidr 0.0.0.0/0 `
                --region $REGION | Out-Null
            
            Write-Host "Successfully added public access rule for port 8080" -ForegroundColor Green
        } catch {
            Write-Host "Note: Rule may already exist. Continuing..." -ForegroundColor Yellow
        }
    }
}

# Verify the rule
Write-Host "`nVerifying security group rules..." -ForegroundColor Cyan
$VERIFIED_RULES = aws ec2 describe-security-groups `
    --group-ids $SG_ID `
    --region $REGION `
    --query "SecurityGroups[0].IpPermissions[?FromPort==`\`"8080`\`" && ToPort==`\`"8080`\`" && IpProtocol==`\`"tcp`\`"]" | ConvertFrom-Json

Write-Host "`nCurrent port 8080 rules:" -ForegroundColor Cyan
if ($VERIFIED_RULES.Count -gt 0) {
    foreach ($rule in $VERIFIED_RULES) {
        Write-Host "  Protocol: $($rule.IpProtocol)" -ForegroundColor White
        Write-Host "  Port: $($rule.FromPort)" -ForegroundColor White
        Write-Host "  Source IPs:" -ForegroundColor White
        foreach ($ipRange in $rule.IpRanges) {
            Write-Host "    - $($ipRange.CidrIp)" -ForegroundColor Green
        }
    }
} else {
    Write-Host "  No rules found for port 8080!" -ForegroundColor Red
}

# Get public IP
Write-Host "`nGetting service public IP..." -ForegroundColor Cyan
$TASK_ARN = aws ecs list-tasks `
    --cluster $CLUSTER_NAME `
    --service-name $SERVICE_NAME `
    --region $REGION `
    --query "taskArns[0]" `
    --output text

if ($TASK_ARN -and $TASK_ARN -ne "None") {
    $NETWORK_INTERFACE_ID = aws ecs describe-tasks `
        --cluster $CLUSTER_NAME `
        --tasks $TASK_ARN `
        --region $REGION `
        --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" `
        --output text
    
    if ($NETWORK_INTERFACE_ID) {
        $PUBLIC_IP = aws ec2 describe-network-interfaces `
            --network-interface-ids $NETWORK_INTERFACE_ID `
            --region $REGION `
            --query "NetworkInterfaces[0].Association.PublicIp" `
            --output text
        
        Write-Host "`n==========================================" -ForegroundColor Green
        Write-Host "Security Group Fixed!" -ForegroundColor Green
        Write-Host "==========================================" -ForegroundColor Green
        Write-Host "Public IP: $PUBLIC_IP" -ForegroundColor White
        Write-Host "Access your app at: http://$PUBLIC_IP:8080" -ForegroundColor White
        Write-Host "`nNote: It may take a few seconds for the changes to propagate." -ForegroundColor Yellow
    }
}

