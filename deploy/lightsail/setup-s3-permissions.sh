#!/bin/bash

# Script to attach S3 permissions to Lightsail container service
# This grants the container service IAM role access to the S3 bucket

set -e  # Exit on error

SERVICE_NAME="stock-analysis"
REGION="eu-central-1"
BUCKET_NAME="stock-analysis-data-3666"
POLICY_NAME="LightsailContainerServiceS3Access"

echo "Setting up S3 permissions for Lightsail container service"
echo "Service: $SERVICE_NAME"
echo "Bucket: $BUCKET_NAME"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY_JSON_PATH="$(dirname "$SCRIPT_DIR")/s3-policy.json"

# Check if policy JSON file exists
if [ ! -f "$POLICY_JSON_PATH" ]; then
    echo "Error: S3 policy file not found: $POLICY_JSON_PATH"
    exit 1
fi

# Get the container service principal ARN (IAM role)
echo "Fetching container service IAM role..."
SERVICE_JSON=$(aws lightsail get-container-services --region "$REGION" --output json)
ROLE_ARN=$(echo "$SERVICE_JSON" | jq -r ".containerServices[] | select(.containerServiceName == \"$SERVICE_NAME\") | .principalArn")

if [ -z "$ROLE_ARN" ] || [ "$ROLE_ARN" == "null" ]; then
    echo "Error: Container service '$SERVICE_NAME' not found or no IAM role!"
    exit 1
fi

echo "Container service role: $ROLE_ARN"

# Extract the role name from the ARN
# Format: arn:aws:iam::ACCOUNT:role/amazon/lightsail/REGION/containers/SERVICE/ROLE_ID
# The role name is everything after /role/
ROLE_NAME=$(echo "$ROLE_ARN" | sed 's|^arn:aws:iam::[^:]*:role/||')
ACCOUNT_ID=$(echo "$ROLE_ARN" | cut -d: -f5)

echo "Role name: $ROLE_NAME"
echo "Account ID: $ACCOUNT_ID"
echo ""

POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"

# Check if policy already exists
echo "Checking if policy '$POLICY_NAME' already exists..."
if aws iam get-policy --policy-arn "$POLICY_ARN" &>/dev/null; then
    echo "Policy already exists. Updating policy version..."
    
    # Create new policy version
    POLICY_VERSION=$(aws iam create-policy-version \
        --policy-arn "$POLICY_ARN" \
        --policy-document "file://$POLICY_JSON_PATH" \
        --set-as-default \
        --output json | jq -r '.PolicyVersion.VersionId')
    
    echo "Policy version created: $POLICY_VERSION"
    
    # List old versions and delete non-default ones (keep last 4)
    VERSIONS_JSON=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" --output json)
    echo "$VERSIONS_JSON" | jq -r '.Versions[] | select(.IsDefaultVersion == false) | .VersionId' | \
        sort -r | tail -n +5 | while read -r version_id; do
        if [ -n "$version_id" ]; then
            echo "Deleting old policy version: $version_id"
            aws iam delete-policy-version \
                --policy-arn "$POLICY_ARN" \
                --version-id "$version_id" 2>/dev/null || true
        fi
    done
else
    echo "Creating new IAM policy: $POLICY_NAME"
    NEW_POLICY=$(aws iam create-policy \
        --policy-name "$POLICY_NAME" \
        --policy-document "file://$POLICY_JSON_PATH" \
        --description "Allows Lightsail container service to access S3 bucket for database persistence" \
        --output json)
    
    echo "Policy created: $(echo "$NEW_POLICY" | jq -r '.Policy.Arn')"
fi

# Check if policy is already attached to the role
echo ""
echo "Checking if policy is attached to role..."
ATTACHED_POLICIES=$(aws iam list-attached-role-policies --role-name "$ROLE_NAME" --output json)

if echo "$ATTACHED_POLICIES" | jq -e ".AttachedPolicies[] | select(.PolicyArn == \"$POLICY_ARN\")" &>/dev/null; then
    echo "Policy is already attached to the role."
else
    echo "Attaching policy to role: $ROLE_NAME"
    
    if aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn "$POLICY_ARN"; then
        echo "Policy attached successfully!"
    else
        echo "Error attaching policy"
        echo ""
        echo "You may need to attach the policy manually:"
        echo "  aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn $POLICY_ARN"
        exit 1
    fi
fi

echo ""
echo "S3 permissions setup complete!"
echo ""
echo "The container service now has access to:"
echo "  - s3:GetObject (download files)"
echo "  - s3:PutObject (upload files)"
echo "  - s3:HeadObject (check if files exist)"
echo "  - s3:DeleteObject (delete files)"
echo "  - s3:ListBucket (list bucket contents)"
echo ""
echo "Bucket: $BUCKET_NAME"
echo ""
echo "Note: It may take a few minutes for the permissions to propagate."
echo "If you still see access denied errors, wait a few minutes and try again."

