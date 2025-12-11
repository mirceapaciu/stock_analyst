# ECS Fargate Deployment - Quick Start

This directory contains scripts and configuration files for deploying the stock analysis app to AWS ECS Fargate with EFS persistent storage.

## What's Included

- **create-efs.sh/ps1** - Creates EFS file system for persistent storage
- **create-cluster.sh/ps1** - Creates ECS cluster
- **task-definition.json** - ECS task definition with EFS mount
- **deploy-service.sh/ps1** - Deploys the ECS service
- **update-task-definition.sh/ps1** - Helper to update task definition with EFS ID
- **ECS_FARGATE_DEPLOYMENT.md** - Complete deployment guide

## Quick Start

### 1. Create IAM Roles

```bash
# Task Execution Role (required)
aws iam create-role --role-name ecsTaskExecutionRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

### 2. Create EFS

```bash
# Linux/Mac
./create-efs.sh

# Windows
.\create-efs.ps1
```

**Save the EFS ID** that's displayed.

### 3. Create Cluster

```bash
# Linux/Mac
./create-cluster.sh

# Windows
.\create-cluster.ps1
```

### 4. Update Task Definition

```bash
# Get your AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Update task definition (replace EFS_ID with value from step 2)
EFS_ID=fs-xxxxx ACCOUNT_ID=$ACCOUNT_ID ./update-task-definition.sh

# Windows
.\update-task-definition.ps1 -EfsId fs-xxxxx -AccountId 123456789
```

### 5. Register Task Definition
Rename task-definition-example.json to task-definition.json and edit the secrets.

WARNING: This method is writing the secrets to the environment variables of the ECS service. They will be visible to anyone who has access to the ECS console!
This is acceptable for a one-user account. For production deployment it is recommended to store the secrets in SSM parameters.

```bash
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json \
  --region eu-central-1
```

### 6. Deploy Service

```bash
# Linux/Mac
./deploy-service.sh

# Windows
.\deploy-service.ps1
```

### 7. ECS Console
ECS console URL: https://eu-central-1.console.aws.amazon.com/ecs/v2/clusters?region=eu-central-1

### 8. Stop the container

#### Option 1: Using the AWS Management Console

    Sign in to your AWS Management Console as root (or preferably an IAM admin user).
    Navigate to ECS (Elastic Container Service).
    In the left menu, choose Clusters.
    Click on the cluster where your service runs.
    Under the Services tab:

        Select your service.

        Click the "Update" or "Delete" button.

        If you click “Update”, then:
            In the “Number of tasks” field, set the desired count to 0.
            Click Next until you can Apply or Update Service.

        This will stop all Fargate tasks but keep your service definition for later reactivation.

        If you click “Delete”, it will remove the service — you can still re-create it later with the same definition or a saved CloudFormation/Terraform stack.

#### Option 2: Using the AWS CLI

##### Stop all tasks in a Fargate service safely
```
aws ecs update-service \
  --cluster <your-cluster-name> \
  --service <your-service-name> \
  --desired-count 0
```
This tells ECS to stop running tasks, but does not delete your configuration.

##### Start the container
You can start the container using:
```
aws ecs update-service \
  --cluster <your-cluster-name> \
  --service <your-service-name> \
  --desired-count 1
```

##### Check That Nothing Is Running
To confirm that no compute is being billed:
```
aws ecs list-tasks --cluster <your-cluster-name>
```
If it returns an empty list ([]), your Fargate tasks are stopped — no Fargate compute billing.


## Key Differences of ECS Fargate from Lightsail

1. **Persistent Storage**: EFS provides direct file system access (no S3 syncing needed)
2. **Reliability**: No race conditions from S3 sync timing
3. **Performance**: Direct file system access is faster than S3
4. **Scalability**: Can run multiple containers sharing the same EFS volume

## Environment Variables

The task definition includes:
- `EFS_MOUNT_PATH=/mnt/efs` - EFS mount point
- `USE_S3_SYNC=false` - Disable S3 syncing (EFS is primary storage)
- Database paths point to `/mnt/efs/data/db/`

## Troubleshooting

See `ECS_FARGATE_DEPLOYMENT.md` for detailed troubleshooting guide.

## Next Steps

- Set up Application Load Balancer for stable endpoint
- Configure auto-scaling
- Set up CloudWatch alarms
- Configure backup strategy (optional)
