#!/bin/bash
# Create EFS file system for persistent storage

set -e

# Configuration
REGION="eu-central-1"
EFS_NAME="stock-analysis-efs"
VPC_ID=""  # Will be detected or set manually
SUBNET_IDS=""  # Will be detected or set manually

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Creating EFS file system for stock analysis app...${NC}"

# Get default VPC if not set
if [ -z "$VPC_ID" ]; then
    echo "Detecting default VPC..."
    VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text --region $REGION)
    if [ "$VPC_ID" == "None" ] || [ -z "$VPC_ID" ]; then
        echo -e "${RED}No default VPC found. Please set VPC_ID manually.${NC}"
        exit 1
    fi
    echo -e "${GREEN}Using VPC: $VPC_ID${NC}"
fi

# Get subnets in the VPC
if [ -z "$SUBNET_IDS" ]; then
    echo "Detecting subnets in VPC..."
    SUBNET_IDS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[*].SubnetId" --output text --region $REGION)
    if [ -z "$SUBNET_IDS" ]; then
        echo -e "${RED}No subnets found in VPC. Please set SUBNET_IDS manually.${NC}"
        exit 1
    fi
    echo -e "${GREEN}Using subnets: $SUBNET_IDS${NC}"
fi

# Check if EFS already exists
EXISTING_EFS=$(aws efs describe-file-systems --region $REGION --query "FileSystems[?Name=='$EFS_NAME'].FileSystemId" --output text)

if [ ! -z "$EXISTING_EFS" ]; then
    echo -e "${YELLOW}EFS file system already exists: $EXISTING_EFS${NC}"
    EFS_ID=$EXISTING_EFS
else
    # Create EFS file system
    echo "Creating EFS file system..."
    EFS_ID=$(aws efs create-file-system \
        --region $REGION \
        --performance-mode generalPurpose \
        --throughput-mode bursting \
        --encrypted \
        --tags "Key=Name,Value=$EFS_NAME" \
        --query "FileSystemId" \
        --output text)
    
    echo -e "${GREEN}Created EFS: $EFS_ID${NC}"
    
    # Wait for EFS to be available
    echo "Waiting for EFS to be available..."
    aws efs wait file-system-available --file-system-id $EFS_ID --region $REGION
fi

# Get security group for EFS (create if doesn't exist)
SG_NAME="efs-sg-$EFS_NAME"
SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
    --query "SecurityGroups[0].GroupId" \
    --output text \
    --region $REGION)

if [ "$SG_ID" == "None" ] || [ -z "$SG_ID" ]; then
    echo "Creating security group for EFS..."
    SG_ID=$(aws ec2 create-security-group \
        --group-name $SG_NAME \
        --description "Security group for EFS access" \
        --vpc-id $VPC_ID \
        --query "GroupId" \
        --output text \
        --region $REGION)
    
    # Allow NFS traffic from VPC
    aws ec2 authorize-security-group-ingress \
        --group-id $SG_ID \
        --protocol tcp \
        --port 2049 \
        --cidr $(aws ec2 describe-vpcs --vpc-ids $VPC_ID --query "Vpcs[0].CidrBlock" --output text --region $REGION) \
        --region $REGION
    
    echo -e "${GREEN}Created security group: $SG_ID${NC}"
else
    echo -e "${GREEN}Using existing security group: $SG_ID${NC}"
fi

# Create mount targets for each subnet
echo "Creating mount targets..."
for SUBNET_ID in $SUBNET_IDS; do
    # Check if mount target already exists
    EXISTING_MT=$(aws efs describe-mount-targets \
        --file-system-id $EFS_ID \
        --region $REGION \
        --query "MountTargets[?SubnetId=='$SUBNET_ID'].MountTargetId" \
        --output text)
    
    if [ -z "$EXISTING_MT" ] || [ "$EXISTING_MT" == "None" ]; then
        echo "Creating mount target for subnet: $SUBNET_ID"
        aws efs create-mount-target \
            --file-system-id $EFS_ID \
            --subnet-id $SUBNET_ID \
            --security-groups $SG_ID \
            --region $REGION
        
        echo -e "${GREEN}Created mount target for subnet: $SUBNET_ID${NC}"
    else
        echo -e "${YELLOW}Mount target already exists for subnet: $SUBNET_ID${NC}"
    fi
done

# Wait for mount targets to be available
echo "Waiting for mount targets to be available..."
for SUBNET_ID in $SUBNET_IDS; do
    MT_ID=$(aws efs describe-mount-targets \
        --file-system-id $EFS_ID \
        --region $REGION \
        --query "MountTargets[?SubnetId=='$SUBNET_ID'].MountTargetId" \
        --output text)
    
    if [ ! -z "$MT_ID" ] && [ "$MT_ID" != "None" ]; then
        aws efs wait mount-target-available --mount-target-id $MT_ID --region $REGION
    fi
done

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}EFS Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "EFS ID: ${GREEN}$EFS_ID${NC}"
echo -e "Security Group: ${GREEN}$SG_ID${NC}"
echo -e "Region: ${GREEN}$REGION${NC}"
echo ""
echo "Save these values for the ECS task definition:"
echo "  EFS_ID=$EFS_ID"
echo "  EFS_SG_ID=$SG_ID"
echo ""
echo "EFS DNS name: $EFS_ID.efs.$REGION.amazonaws.com"
echo ""

