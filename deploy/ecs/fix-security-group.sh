#!/bin/bash
# Fix security group to allow inbound traffic on port 8080

set -e

REGION="eu-central-1"
CLUSTER_NAME="stock-analysis-cluster"
SERVICE_NAME="stock-analysis-service"

echo "Checking ECS service configuration..."

# Get the service to find which security group it's using
SERVICE_JSON=$(aws ecs describe-services \
    --cluster $CLUSTER_NAME \
    --services $SERVICE_NAME \
    --region $REGION \
    --query "services[0]")

if [ -z "$SERVICE_JSON" ] || [ "$SERVICE_JSON" == "null" ]; then
    echo "Error: Service not found!"
    exit 1
fi

# Get security group ID from network configuration
SG_ID=$(echo $SERVICE_JSON | jq -r '.networkConfiguration.awsvpcConfiguration.securityGroups[0]')

if [ -z "$SG_ID" ] || [ "$SG_ID" == "null" ]; then
    echo "Error: No security groups found!"
    exit 1
fi

echo "Service is using security group: $SG_ID"

# Check current inbound rules
echo ""
echo "Checking current security group rules..."
CURRENT_RULES=$(aws ec2 describe-security-groups \
    --group-ids $SG_ID \
    --region $REGION \
    --query "SecurityGroups[0].IpPermissions")

HAS_PORT_8080=$(echo $CURRENT_RULES | jq -r '.[] | select(.FromPort == 8080 and .ToPort == 8080 and .IpProtocol == "tcp") | .FromPort')

if [ -n "$HAS_PORT_8080" ]; then
    echo "Found existing rule for port 8080"
    echo $CURRENT_RULES | jq -r '.[] | select(.FromPort == 8080) | "  Protocol: \(.IpProtocol)\n  Port: \(.FromPort)\n  Source IPs: \(.IpRanges[].CidrIp)"'
    
    # Check if it allows public access
    ALLOWS_PUBLIC=$(echo $CURRENT_RULES | jq -r '.[] | select(.FromPort == 8080) | .IpRanges[] | select(.CidrIp == "0.0.0.0/0") | .CidrIp')
    
    if [ -z "$ALLOWS_PUBLIC" ]; then
        echo ""
        echo "Rule exists but doesn't allow public access (0.0.0.0/0). Adding public access rule..."
        aws ec2 authorize-security-group-ingress \
            --group-id $SG_ID \
            --protocol tcp \
            --port 8080 \
            --cidr 0.0.0.0/0 \
            --region $REGION || echo "Note: Rule may already exist. Continuing..."
    fi
else
    echo "No rule found for port 8080. Adding inbound rule..."
    aws ec2 authorize-security-group-ingress \
        --group-id $SG_ID \
        --protocol tcp \
        --port 8080 \
        --cidr 0.0.0.0/0 \
        --region $REGION
    
    echo "Successfully added inbound rule for port 8080 from 0.0.0.0/0"
fi

# Verify the rule
echo ""
echo "Verifying security group rules..."
VERIFIED_RULES=$(aws ec2 describe-security-groups \
    --group-ids $SG_ID \
    --region $REGION \
    --query "SecurityGroups[0].IpPermissions[?FromPort==\`8080\` && ToPort==\`8080\` && IpProtocol==\`tcp\`]")

echo ""
echo "Current port 8080 rules:"
echo $VERIFIED_RULES | jq -r '.[] | "  Protocol: \(.IpProtocol)\n  Port: \(.FromPort)\n  Source IPs:\n\(.IpRanges[] | "    - \(.CidrIp)")"'

# Get public IP
echo ""
echo "Getting service public IP..."
TASK_ARN=$(aws ecs list-tasks \
    --cluster $CLUSTER_NAME \
    --service-name $SERVICE_NAME \
    --region $REGION \
    --query "taskArns[0]" \
    --output text)

if [ -n "$TASK_ARN" ] && [ "$TASK_ARN" != "None" ]; then
    NETWORK_INTERFACE_ID=$(aws ecs describe-tasks \
        --cluster $CLUSTER_NAME \
        --tasks $TASK_ARN \
        --region $REGION \
        --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" \
        --output text)
    
    if [ -n "$NETWORK_INTERFACE_ID" ]; then
        PUBLIC_IP=$(aws ec2 describe-network-interfaces \
            --network-interface-ids $NETWORK_INTERFACE_ID \
            --region $REGION \
            --query "NetworkInterfaces[0].Association.PublicIp" \
            --output text)
        
        echo ""
        echo "=========================================="
        echo "Security Group Fixed!"
        echo "=========================================="
        echo "Public IP: $PUBLIC_IP"
        echo "Access your app at: http://$PUBLIC_IP:8080"
        echo ""
        echo "Note: It may take a few seconds for the changes to propagate."
    fi
fi

