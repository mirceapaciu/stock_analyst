#!/bin/bash
# Deploy ECS service with Fargate

set -e

# Configuration
CLUSTER_NAME="stock-analysis-cluster"
SERVICE_NAME="stock-analysis-service"
TASK_DEFINITION="stock-analysis-app"
REGION="eu-central-1"
DESIRED_COUNT=1

# Get VPC and subnet configuration
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text --region $REGION)
SUBNET_IDS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[*].SubnetId" --output text --region $REGION | tr '\t' ',')

# Get security group (use default or create one)
SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=default" "Name=vpc-id,Values=$VPC_ID" --query "SecurityGroups[0].GroupId" --output text --region $REGION)

echo "Deploying ECS service..."
echo "Cluster: $CLUSTER_NAME"
echo "Service: $SERVICE_NAME"
echo "VPC: $VPC_ID"
echo "Subnets: $SUBNET_IDS"
echo "Security Group: $SG_ID"

# Check if service already exists
EXISTING_SERVICE=$(aws ecs describe-services --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION --query "services[0].serviceName" --output text 2>/dev/null || echo "")

if [ "$EXISTING_SERVICE" == "$SERVICE_NAME" ]; then
    echo "Service already exists. Updating..."
    aws ecs update-service \
        --cluster $CLUSTER_NAME \
        --service $SERVICE_NAME \
        --task-definition $TASK_DEFINITION \
        --desired-count $DESIRED_COUNT \
        --region $REGION \
        --force-new-deployment
    
    echo "Service updated. Waiting for deployment to stabilize..."
    aws ecs wait services-stable --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION
else
    echo "Creating new service..."
    aws ecs create-service \
        --cluster $CLUSTER_NAME \
        --service-name $SERVICE_NAME \
        --task-definition $TASK_DEFINITION \
        --desired-count $DESIRED_COUNT \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_IDS],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
        --region $REGION \
        --health-check-grace-period-seconds 60
    
    echo "Service created. Waiting for service to be stable..."
    aws ecs wait services-stable --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION
fi

# Get service details and ensure security group allows port 8080
echo "Configuring security group for port 8080..."

# Check if jq is available
if command -v jq &> /dev/null; then
    USE_JQ=true
else
    USE_JQ=false
    echo "Note: jq not found. Using AWS CLI queries (may be less robust)."
fi

SERVICE_ARN=$(aws ecs describe-services --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION --query "services[0].serviceArn" --output text)

# Get the actual security group ID from the service (in case it changed)
if [ "$USE_JQ" = true ]; then
    SERVICE_JSON=$(aws ecs describe-services --cluster $CLUSTER_NAME --services $SERVICE_NAME --region $REGION --query "services[0]")
    SERVICE_SG_ID=$(echo $SERVICE_JSON | jq -r '.networkConfiguration.awsvpcConfiguration.securityGroups[0]')
    if [ -z "$SERVICE_SG_ID" ] || [ "$SERVICE_SG_ID" == "null" ]; then
        SERVICE_SG_ID=$SG_ID
    fi
else
    # Fallback: use the security group we started with
    SERVICE_SG_ID=$SG_ID
fi

# Check if port 8080 rule exists and allows public access
if [ "$USE_JQ" = true ]; then
    CURRENT_RULES=$(aws ec2 describe-security-groups --group-ids $SERVICE_SG_ID --region $REGION --query "SecurityGroups[0].IpPermissions")
    HAS_PORT_8080=$(echo $CURRENT_RULES | jq -r '.[] | select(.FromPort == 8080 and .ToPort == 8080 and .IpProtocol == "tcp") | .FromPort')
    ALLOWS_PUBLIC=$(echo $CURRENT_RULES | jq -r '.[] | select(.FromPort == 8080) | .IpRanges[] | select(.CidrIp == "0.0.0.0/0") | .CidrIp')
else
    # Fallback: try to add the rule (will fail gracefully if it exists)
    HAS_PORT_8080=""
    ALLOWS_PUBLIC=""
fi

if [ -z "$HAS_PORT_8080" ] || [ -z "$ALLOWS_PUBLIC" ]; then
    echo "Adding inbound rule for port 8080 from 0.0.0.0/0..."
    aws ec2 authorize-security-group-ingress \
        --group-id $SERVICE_SG_ID \
        --protocol tcp \
        --port 8080 \
        --cidr 0.0.0.0/0 \
        --region $REGION 2>/dev/null || echo "Note: Rule may already exist."
    echo "Security group rule added successfully."
else
    echo "Security group already allows port 8080."
fi

TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER_NAME --service-name $SERVICE_NAME --region $REGION --query "taskArns[0]" --output text)

if [ ! -z "$TASK_ARN" ] && [ "$TASK_ARN" != "None" ]; then
    # Get public IP
    PUBLIC_IP=$(aws ecs describe-tasks --cluster $CLUSTER_NAME --tasks $TASK_ARN --region $REGION --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" --output text | xargs -I {} aws ec2 describe-network-interfaces --network-interface-ids {} --region $REGION --query "NetworkInterfaces[0].Association.PublicIp" --output text)
    
    echo ""
    echo "=========================================="
    echo "Deployment Complete!"
    echo "=========================================="
    echo "Service ARN: $SERVICE_ARN"
    echo "Public IP: $PUBLIC_IP"
    echo "Access your app at: http://$PUBLIC_IP:8080"
    echo ""
else
    echo ""
    echo "Service deployed. Check AWS Console for task details."
    echo ""
fi

