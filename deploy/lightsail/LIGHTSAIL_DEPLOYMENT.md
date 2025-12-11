# AWS Lightsail Container Service Deployment Guide

This guide explains how to deploy your application to AWS Lightsail Container Service with secure environment variable management.

## Overview

There are three main approaches to managing environment variables in AWS Lightsail:

1. **Direct Environment Variables** (Simplest) - Set via AWS CLI or Console
2. **AWS Systems Manager Parameter Store** (Recommended) - Secure, centralized secret management
3. **Startup Script** - Fetch from SSM at container startup

## Prerequisites

- AWS CLI configured with appropriate credentials
- Docker image pushed to a container registry (Docker Hub, ECR, etc.)
- AWS Lightsail Container Service created

## Option 1: Direct Environment Variables (Simplest)

### Using AWS CLI

Update your container service deployment with environment variables:

```bash
# Create or update container service deployment
aws lightsail create-container-service-deployment \
  --service-name stock-analysis-app \
  --cli-input-json file://lightsail-deployment.json
```

**Important**: Remove hardcoded API keys from `lightsail-deployment.json` and set them via AWS CLI instead:

```bash
# Set environment variables via AWS CLI
aws lightsail update-container-service \
  --service-name stock-analysis-app \
  --power small \
  --scale 1 \
  --public-endpoint-containerName app \
  --public-endpoint-containerPort 8080 \
  --public-endpoint-healthCheck-path "/_stcore/health"
```

Then update the deployment JSON to use environment variable placeholders or set them via the console.

### Using AWS Console

1. Go to AWS Lightsail → Container Services
2. Select your container service
3. Click "Modify and deploy a new version"
4. Under "Environment variables", add your variables:
   - `OPENAI_API_KEY`
   - `GOOGLE_API_KEY`
   - `GOOGLE_CSE_ID`
   - `FINNHUB_API_KEY`
   - `FMP_API_KEY`
   - `MAX_WORKERS=2`
   - `OPENAI_MODEL=gpt-4o-mini`
   - `MAX_PE_RATIO=15.0`
   - `MIN_MARKET_CAP=1000000000`

## Option 2: AWS Systems Manager Parameter Store (Recommended)

### Step 1: Store Secrets in SSM Parameter Store

Use the provided script to store your API keys securely:

```bash
# Run the commands from aws_parameter_commands.txt
aws ssm put-parameter \
  --name "/stock-analysis/openai-api-key" \
  --value "your-openai-key" \
  --type "SecureString" \
  --region eu-central-1 \
  --overwrite

aws ssm put-parameter \
  --name "/stock-analysis/google-api-key" \
  --value "your-google-key" \
  --type "SecureString" \
  --region eu-central-1 \
  --overwrite

aws ssm put-parameter \
  --name "/stock-analysis/google-cse-id" \
  --value "your-cse-id" \
  --type "String" \
  --region eu-central-1 \
  --overwrite

aws ssm put-parameter \
  --name "/stock-analysis/finnhub-api-key" \
  --value "your-finnhub-key" \
  --type "SecureString" \
  --region eu-central-1 \
  --overwrite

aws ssm put-parameter \
  --name "/stock-analysis/fmp-api-key" \
  --value "your-fmp-key" \
  --type "SecureString" \
  --region eu-central-1 \
  --overwrite

# Optional: Store configuration values
aws ssm put-parameter \
  --name "/stock-analysis/max-workers" \
  --value "2" \
  --type "String" \
  --region eu-central-1 \
  --overwrite
```

### Step 2: Grant IAM Permissions

Your Lightsail container service needs IAM permissions to read from SSM. Create an IAM policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters"
      ],
      "Resource": "arn:aws:ssm:eu-central-1:*:parameter/stock-analysis/*"
    }
  ]
}
```

Attach this policy to your Lightsail container service's execution role.

### Step 3: Use Startup Script (Optional)

If you want to fetch from SSM at runtime, modify your Dockerfile to use the entrypoint script (see Option 3).

## Option 3: Startup Script with SSM Integration

This approach uses a Python script to fetch environment variables from SSM at container startup.

### Step 1: Update Dockerfile

Modify your Dockerfile to include the startup script:

```dockerfile
# ... existing Dockerfile content ...

# Copy startup scripts
COPY scripts/load_env_from_ssm.py ./scripts/
COPY scripts/entrypoint.sh ./scripts/
RUN chmod +x ./scripts/entrypoint.sh

# Use entrypoint script
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["streamlit", "run", "src/ui/main_app.py", \
    "--server.port=8080", \
    "--server.address=0.0.0.0", \
    "--server.headless=true", \
    "--server.enableCORS=false", \
    "--server.enableXsrfProtection=false", \
    "--server.enableWebsocketCompression=false"]
```

### Step 2: Set IAM Permissions

Ensure your container has IAM permissions to access SSM (see Option 2, Step 2).

### Step 3: Deploy

The container will automatically fetch environment variables from SSM on startup.

## Recommended Approach for Lightsail

**For AWS Lightsail, I recommend Option 1 (Direct Environment Variables)** because:

1. Lightsail Container Service doesn't have native SSM integration like ECS/Fargate
2. It's simpler and doesn't require IAM role configuration
3. Environment variables are still secure (not in code/containers)
4. Easy to update via console or CLI

However, if you need centralized secret management across multiple services, use Option 2 with the startup script.

## Environment Variables Reference

### Required Variables

- `OPENAI_API_KEY` - OpenAI API key
- `GOOGLE_API_KEY` - Google Custom Search API key
- `GOOGLE_CSE_ID` - Google Custom Search Engine ID
- `FINNHUB_API_KEY` - Finnhub API key
- `FMP_API_KEY` - Financial Modeling Prep API key

### Optional Variables

- `MAX_WORKERS` - Thread pool workers (default: 5, recommended for Lightsail: 2)
- `OPENAI_MODEL` - OpenAI model (default: gpt-4o-mini)
- `MAX_PE_RATIO` - Maximum P/E ratio filter (default: 15.0)
- `MIN_MARKET_CAP` - Minimum market cap in USD (default: 1000000000)
- `AWS_DEFAULT_REGION` - AWS region (default: eu-central-1)
- `S3_BUCKET` - S3 bucket name (if using S3 storage)

## Security Best Practices

1. **Never commit API keys to Git** - Use `.gitignore` for files containing secrets
2. **Use SSM Parameter Store** for production secrets
3. **Rotate API keys regularly**
4. **Use least-privilege IAM policies**
5. **Enable CloudWatch logging** to monitor access

## Updating Environment Variables

### Via AWS Console

1. Navigate to Lightsail → Container Services
2. Select your service
3. Click "Modify and deploy a new version"
4. Update environment variables
5. Deploy new version

### Via AWS CLI

```bash
# Update the lightsail-deployment.json file with new values
# Then deploy:
aws lightsail create-container-service-deployment \
  --service-name stock-analysis-app \
  --cli-input-json file://lightsail-deployment.json
```

## Troubleshooting

### Container fails to start

Check CloudWatch logs:
```bash
aws lightsail get-container-log \
  --service-name stock-analysis-app \
  --container-name app
```

### Environment variables not loading

1. Verify variables are set in Lightsail console
2. Check container logs for errors
3. Ensure variable names match exactly (case-sensitive)

### SSM Parameter Store access denied

1. Verify IAM role has `ssm:GetParameter` permission
2. Check parameter names match exactly
3. Verify region is correct

## Example lightsail-deployment.json (Secure Version)

```json
{
  "containers": {
    "app": {
      "image": "mirceapaciu/stock-analysis-app:latest",
      "environment": {
        "MAX_WORKERS": "2",
        "OPENAI_MODEL": "gpt-4o-mini",
        "MAX_PE_RATIO": "15.0",
        "MIN_MARKET_CAP": "1000000000",
        "AWS_DEFAULT_REGION": "eu-central-1",
        "S3_BUCKET": "stock-analysis-data-3666"
      },
      "ports": {
        "8080": "HTTP"
      }
    }
  },
  "publicEndpoint": {
    "containerName": "app",
    "containerPort": 8080,
    "healthCheck": {
      "path": "/_stcore/health",
      "intervalSeconds": 10,
      "timeoutSeconds": 5,
      "healthyThreshold": 2,
      "unhealthyThreshold": 3,
      "successCodes": "200-499"
    }
  }
}
```

**Note**: API keys should be set via AWS Console or CLI, not in this JSON file.

