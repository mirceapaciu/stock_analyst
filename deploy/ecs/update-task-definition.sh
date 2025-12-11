#!/bin/bash
# Helper script to update task definition with EFS ID and account ID

set -e

TASK_DEF_FILE="task-definition.json"
EFS_ID="${EFS_ID:-}"
ACCOUNT_ID="${ACCOUNT_ID:-}"

if [ -z "$EFS_ID" ]; then
    echo "Error: EFS_ID environment variable not set"
    echo "Usage: EFS_ID=fs-xxxxx ACCOUNT_ID=123456789 ./update-task-definition.sh"
    exit 1
fi

if [ -z "$ACCOUNT_ID" ]; then
    echo "Error: ACCOUNT_ID environment variable not set"
    echo "Usage: EFS_ID=fs-xxxxx ACCOUNT_ID=123456789 ./update-task-definition.sh"
    exit 1
fi

echo "Updating task definition..."
echo "EFS ID: $EFS_ID"
echo "Account ID: $ACCOUNT_ID"

# Update EFS ID
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sed -i '' "s/EFS_FILE_SYSTEM_ID/$EFS_ID/g" "$TASK_DEF_FILE"
    sed -i '' "s/ACCOUNT_ID/$ACCOUNT_ID/g" "$TASK_DEF_FILE"
else
    # Linux
    sed -i "s/EFS_FILE_SYSTEM_ID/$EFS_ID/g" "$TASK_DEF_FILE"
    sed -i "s/ACCOUNT_ID/$ACCOUNT_ID/g" "$TASK_DEF_FILE"
fi

echo "Task definition updated successfully!"
echo "Review $TASK_DEF_FILE before registering"

