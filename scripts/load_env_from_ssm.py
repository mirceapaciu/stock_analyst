#!/usr/bin/env python3
"""
Load environment variables from AWS Systems Manager Parameter Store.
This script can be used as an entrypoint to fetch secrets before starting the app.
"""

import os
import sys
import boto3
from botocore.exceptions import ClientError

# SSM Parameter Store prefix
SSM_PREFIX = os.getenv("SSM_PREFIX", "/stock-analysis")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")

# Map of environment variable names to SSM parameter names
ENV_TO_SSM = {
    "OPENAI_API_KEY": f"{SSM_PREFIX}/openai-api-key",
    "GOOGLE_API_KEY": f"{SSM_PREFIX}/google-api-key",
    "GOOGLE_CSE_ID": f"{SSM_PREFIX}/google-cse-id",
    "FINNHUB_API_KEY": f"{SSM_PREFIX}/finnhub-api-key",
    "FMP_API_KEY": f"{SSM_PREFIX}/fmp-api-key",
}

def load_from_ssm():
    """Load environment variables from SSM Parameter Store."""
    try:
        ssm = boto3.client("ssm", region_name=AWS_REGION)
        
        for env_var, ssm_param in ENV_TO_SSM.items():
            # Skip if already set (allows override)
            if os.getenv(env_var):
                continue
                
            try:
                # Try to get the parameter
                response = ssm.get_parameter(Name=ssm_param, WithDecryption=True)
                value = response["Parameter"]["Value"]
                os.environ[env_var] = value
                print(f"Loaded {env_var} from SSM", file=sys.stderr)
            except ClientError as e:
                if e.response["Error"]["Code"] == "ParameterNotFound":
                    # Parameter doesn't exist, skip it
                    print(f"Warning: SSM parameter {ssm_param} not found, skipping", file=sys.stderr)
                else:
                    print(f"Error loading {ssm_param}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Error connecting to SSM: {e}", file=sys.stderr)
        print("Continuing with existing environment variables...", file=sys.stderr)

if __name__ == "__main__":
    # Load environment variables from SSM
    load_from_ssm()
    
    # Execute the command passed as arguments
    # Note: os.execvp() replaces the current process but inherits all environment
    # variables that were set above. The Streamlit process will have access to
    # all environment variables loaded from SSM.
    if len(sys.argv) > 1:
        # Replace this process with the command (inherits environment)
        os.execvp(sys.argv[1], sys.argv[1:])
    else:
        print("No command provided", file=sys.stderr)
        sys.exit(1)

