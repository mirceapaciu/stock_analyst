# AWS ECS Fargate Deployment Guide

This guide explains how to deploy the application to AWS ECS Fargate with EFS for persistent storage.

## Overview

ECS Fargate provides serverless container hosting with persistent storage via EFS (Elastic File System). This eliminates the need for S3 syncing and provides reliable, direct file system access.

### Architecture

```
ECS Fargate Container → EFS Mount (/mnt/efs) → SQLite/DuckDB Files
```

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **Docker image** pushed to a container registry (Docker Hub, ECR, etc.)
3. **IAM Roles** created for ECS tasks
4. **VPC** with subnets (default VPC works fine)

## Step 1: Create IAM Roles

ECS requires two IAM roles:

### 1.1 Task Execution Role

This role allows ECS to pull images and write logs:

```bash
# Create trust policy
cat > trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create role
aws iam create-role \
  --role-name ecsTaskExecutionRole \
  --assume-role-policy-document file://trust-policy.json

# Attach managed policy
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Add EFS access (if using access points)
aws iam put-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-name EFSAccess \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "elasticfilesystem:ClientMount",
        "elasticfilesystem:ClientWrite",
        "elasticfilesystem:ClientRootAccess"
      ],
      "Resource": "*"
    }]
  }'
```

### 1.2 Task Role (Optional)

For accessing other AWS services (S3, SSM, etc.):

```bash
# Create task role
aws iam create-role \
  --role-name ecsTaskRole \
  --assume-role-policy-document file://trust-policy.json

# Attach policies as needed (e.g., S3 read/write, SSM parameter access)
```

**Note:** Replace `ACCOUNT_ID` in `task-definition.json` with your AWS account ID.

## Step 2: Create EFS File System

EFS provides persistent storage that survives container restarts.

### Using Scripts

**Linux/Mac:**
```bash
cd deploy/ecs
chmod +x create-efs.sh
./create-efs.sh
```

**Windows:**
```powershell
cd deploy\ecs
.\create-efs.ps1
```

### Manual Creation

```bash
# Create EFS
EFS_ID=$(aws efs create-file-system \
  --region eu-central-1 \
  --performance-mode generalPurpose \
  --throughput-mode provisioned \
  --provisioned-throughput-in-mibps 100 \
  --encrypted \
  --tags "Key=Name,Value=stock-analysis-efs" \
  --query "FileSystemId" \
  --output text)

# Create security group for EFS
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text --region eu-central-1)

SG_ID=$(aws ec2 create-security-group \
  --group-name efs-sg-stock-analysis \
  --description "Security group for EFS" \
  --vpc-id $VPC_ID \
  --query "GroupId" \
  --output text \
  --region eu-central-1)

# Allow NFS traffic
VPC_CIDR=$(aws ec2 describe-vpcs --vpc-ids $VPC_ID --query "Vpcs[0].CidrBlock" --output text --region eu-central-1)

aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 2049 \
  --cidr $VPC_CIDR \
  --region eu-central-1

# Create mount targets in each subnet
SUBNET_IDS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[*].SubnetId" --output text --region eu-central-1)

for SUBNET_ID in $SUBNET_IDS; do
  aws efs create-mount-target \
    --file-system-id $EFS_ID \
    --subnet-id $SUBNET_ID \
    --security-groups $SG_ID \
    --region eu-central-1
done
```

**Save the EFS ID** - you'll need it for the task definition.

## Step 3: Create ECS Cluster

### Using Scripts

**Linux/Mac:**
```bash
cd deploy/ecs
chmod +x create-cluster.sh
./create-cluster.sh
```

**Windows:**
```powershell
cd deploy\ecs
.\create-cluster.ps1
```

### Manual Creation

```bash
# Create cluster
aws ecs create-cluster \
  --cluster-name stock-analysis-cluster \
  --region eu-central-1 \
  --capacity-providers FARGATE FARGATE_SPOT \
  --default-capacity-provider-strategy capacityProvider=FARGATE,weight=1

# Create CloudWatch log group
aws logs create-log-group \
  --log-group-name /ecs/stock-analysis-app \
  --region eu-central-1
```

## Step 4: Update Task Definition

1. Edit `deploy/ecs/task-definition.json`
2. Replace `ACCOUNT_ID` with your AWS account ID
3. Replace `EFS_FILE_SYSTEM_ID` with your EFS ID from Step 2
4. Update environment variables as needed
5. Update image tag if needed

### Key Configuration

- **EFS Mount Path:** `/mnt/efs` (configurable via `EFS_MOUNT_PATH` env var)
- **Database Paths:** 
  - Recommendations: `/mnt/efs/data/db/recommendations.db`
  - Stocks: `/mnt/efs/data/db/stocks.duckdb`

## Step 5: Register Task Definition

```bash
cd deploy/ecs

# Register task definition
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region eu-central-1
```

## Step 6: Deploy Service

### Using Scripts

**Linux/Mac:**
```bash
cd deploy/ecs
chmod +x deploy-service.sh
./deploy-service.sh
```

**Windows:**
```powershell
cd deploy\ecs
.\deploy-service.ps1
```

**Note:** The deployment scripts automatically configure the security group to allow inbound traffic on port 8080 from the internet (0.0.0.0/0). This is required for your application to be accessible.

### Manual Deployment

```bash
# Get VPC and subnet info
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text --region eu-central-1)
SUBNET_IDS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[*].SubnetId" --output text --region eu-central-1 | tr '\t' ',')
SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=default" "Name=vpc-id,Values=$VPC_ID" --query "SecurityGroups[0].GroupId" --output text --region eu-central-1)

# Create service
aws ecs create-service \
  --cluster stock-analysis-cluster \
  --service-name stock-analysis-service \
  --task-definition stock-analysis-app \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_IDS],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
  --region eu-central-1 \
  --health-check-grace-period-seconds 60

# Configure security group to allow inbound traffic on port 8080
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 8080 \
  --cidr 0.0.0.0/0 \
  --region eu-central-1
```

## Step 7: Access Your Application

After deployment, get the public IP:

```bash
# Get task ARN
TASK_ARN=$(aws ecs list-tasks \
  --cluster stock-analysis-cluster \
  --service-name stock-analysis-service \
  --region eu-central-1 \
  --query "taskArns[0]" \
  --output text)

# Get network interface
NETWORK_INTERFACE_ID=$(aws ecs describe-tasks \
  --cluster stock-analysis-cluster \
  --tasks $TASK_ARN \
  --region eu-central-1 \
  --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value" \
  --output text)

# Get public IP
PUBLIC_IP=$(aws ec2 describe-network-interfaces \
  --network-interface-ids $NETWORK_INTERFACE_ID \
  --region eu-central-1 \
  --query "NetworkInterfaces[0].Association.PublicIp" \
  --output text)

echo "Access your app at: http://$PUBLIC_IP:8080"
```

## Updating the Deployment

### Update Task Definition

1. Edit `task-definition.json`
2. Register new revision:
```bash
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region eu-central-1
```

3. Force new deployment:
```bash
aws ecs update-service \
  --cluster stock-analysis-cluster \
  --service stock-analysis-service \
  --task-definition stock-analysis-app \
  --force-new-deployment \
  --region eu-central-1
```

### Update Docker Image

1. Build and push new image:
```bash
docker build -t mirceapaciu/stock-analysis-app:latest .
docker push mirceapaciu/stock-analysis-app:latest
```

2. Force new deployment (as above)

## Environment Variables

Set environment variables in the task definition or use AWS Systems Manager Parameter Store:

### Using Parameter Store

1. Store secrets in Parameter Store:
```bash
aws ssm put-parameter \
  --name "/stock-analysis/OPENAI_API_KEY" \
  --value "your-key" \
  --type "SecureString" \
  --region eu-central-1
```

2. Reference in task definition (requires task execution role with SSM permissions)

## Monitoring

### View Logs

```bash
# Stream logs
aws logs tail /ecs/stock-analysis-app --follow --region eu-central-1

# Or view in CloudWatch Console
```

### Check Service Status

```bash
aws ecs describe-services \
  --cluster stock-analysis-cluster \
  --services stock-analysis-service \
  --region eu-central-1
```

## Troubleshooting

### Quick Fix Scripts

If you encounter connection issues, use the security group fix scripts:

**Linux/Mac:**
```bash
cd deploy/ecs
chmod +x fix-security-group.sh
./fix-security-group.sh
```

**Windows:**
```powershell
cd deploy\ecs
.\fix-security-group.ps1
```

These scripts automatically detect and fix missing security group rules for port 8080.

### Container Won't Start

1. Check CloudWatch logs
2. Verify EFS mount is working
3. Check task execution role permissions
4. Verify security groups allow traffic

### Database Issues

1. Verify EFS is mounted: Check logs for mount errors
2. Check file permissions on EFS
3. Verify database paths in environment variables

### Network Issues

1. **Connection Timeout (ERR_CONNECTION_TIMED_OUT):**
   - Verify security group allows inbound traffic on port 8080 from 0.0.0.0/0
   - The deployment scripts automatically configure this, but if deploying manually, run:
     ```bash
     aws ec2 authorize-security-group-ingress \
       --group-id <SECURITY_GROUP_ID> \
       --protocol tcp \
       --port 8080 \
       --cidr 0.0.0.0/0 \
       --region eu-central-1
     ```
   - Or use the fix script: `./fix-security-group.sh` (Linux/Mac) or `.\fix-security-group.ps1` (Windows)
2. Check that public IP is assigned
3. Verify VPC has internet gateway
4. Wait a few seconds after adding security group rules for changes to propagate

## Cost Considerations

- **Fargate:** ~$0.04/vCPU-hour + ~$0.004/GB-hour
- **EFS:** ~$0.30/GB-month (provisioned throughput: $6/MiBps-month)
- **Data Transfer:** Standard AWS data transfer pricing

For a small app (1 vCPU, 2GB RAM, 10GB EFS):
- Fargate: ~$30/month (if running 24/7)
- EFS: ~$3/month + throughput costs

## Migration from Lightsail

1. Export data from Lightsail (if using S3, data is already there)
2. Set up ECS Fargate + EFS
3. Import data to EFS (if needed)
4. Update DNS/load balancer to point to new service
5. Monitor and verify
6. Decommission Lightsail service

## Next Steps

- Set up Application Load Balancer for stable endpoint
- Configure auto-scaling
- Set up CloudWatch alarms
- Configure backup strategy for EFS (optional, EFS is already durable)

