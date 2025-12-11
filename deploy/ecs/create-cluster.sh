#!/bin/bash
# Create ECS cluster for Fargate

set -e

CLUSTER_NAME="stock-analysis-cluster"
REGION="eu-central-1"

echo "Creating ECS cluster: $CLUSTER_NAME"

# Check if cluster already exists
EXISTING_CLUSTER=$(aws ecs describe-clusters --clusters $CLUSTER_NAME --region $REGION --query "clusters[0].clusterName" --output text 2>/dev/null || echo "")

if [ "$EXISTING_CLUSTER" == "$CLUSTER_NAME" ]; then
    echo "Cluster already exists: $CLUSTER_NAME"
else
    # Create cluster
    aws ecs create-cluster \
        --cluster-name $CLUSTER_NAME \
        --region $REGION \
        --capacity-providers FARGATE FARGATE_SPOT \
        --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1
    
    echo "Created cluster: $CLUSTER_NAME"
fi

# Create CloudWatch log group
LOG_GROUP="/ecs/stock-analysis-app"
EXISTING_LOG_GROUP=$(aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP --region $REGION --query "logGroups[0].logGroupName" --output text 2>/dev/null || echo "")

if [ "$EXISTING_LOG_GROUP" == "$LOG_GROUP" ]; then
    echo "Log group already exists: $LOG_GROUP"
else
    aws logs create-log-group \
        --log-group-name $LOG_GROUP \
        --region $REGION
    echo "Created log group: $LOG_GROUP"
fi

echo ""
echo "Cluster setup complete!"
echo "Cluster name: $CLUSTER_NAME"
echo "Region: $REGION"

