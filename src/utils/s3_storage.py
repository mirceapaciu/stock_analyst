"""S3 storage utilities for persisting SQLite databases."""

import os
import logging
from pathlib import Path
from typing import Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Storage:
    """Manages S3 storage for SQLite database files."""
    
    def __init__(self, bucket_name: Optional[str] = None):
        """Initialize S3 client.
        
        Args:
            bucket_name: S3 bucket name. Defaults to S3_BUCKET env variable.
        """
        self.bucket_name = bucket_name or os.getenv('S3_BUCKET')
        self.region = os.getenv('AWS_DEFAULT_REGION', 'eu-central-1')
        
        if not self.bucket_name:
            use_s3_sync = os.getenv("USE_S3_SYNC", "true").lower() == "true"
            if use_s3_sync:
                logger.warning("S3_BUCKET not configured. S3 backup/restore disabled. Database persistence may still be available via EFS or local storage.")
            else:
                logger.debug("S3_BUCKET not configured and USE_S3_SYNC=false. S3 backup disabled (using EFS/local storage).")
            self.s3_client = None
            return
            
        try:
            self.s3_client = boto3.client('s3', region_name=self.region)
            logger.info(f"S3 storage initialized: bucket={self.bucket_name}, region={self.region}")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            self.s3_client = None
    
    def download_if_exists(self, s3_key: str, local_path: str) -> bool:
        """Download file from S3 if it exists.
        
        Args:
            s3_key: S3 object key (path in bucket)
            local_path: Local file path to download to
            
        Returns:
            True if file was downloaded, False if it doesn't exist or on error
        """
        if not self.s3_client:
            return False
            
        try:
            # Ensure local directory exists
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Check if file exists in S3
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            
            # Download file
            self.s3_client.download_file(self.bucket_name, s3_key, local_path)
            logger.info(f"Downloaded from S3: {s3_key} -> {local_path}")
            return True
            
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                logger.info(f"File not found in S3: {s3_key} (will be created on first save)")
                return False
            else:
                logger.error(f"Error downloading from S3: {e}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error downloading from S3: {e}")
            return False
    
    def upload(self, local_path: str, s3_key: str) -> bool:
        """Upload file to S3.
        
        Args:
            local_path: Local file path to upload
            s3_key: S3 object key (path in bucket)
            
        Returns:
            True if upload succeeded, False otherwise
        """
        if not self.s3_client:
            return False
            
        if not Path(local_path).exists():
            logger.warning(f"Local file not found, skipping upload: {local_path}")
            return False
            
        try:
            self.s3_client.upload_file(local_path, self.bucket_name, s3_key)
            logger.info(f"Uploaded to S3: {local_path} -> {s3_key}")
            return True
        except Exception as e:
            logger.error(f"Error uploading to S3: {e}")
            return False
    
    def sync_database_from_s3(self, db_path: str, s3_key: Optional[str] = None) -> bool:
        """Download database from S3 if it exists.
        
        Args:
            db_path: Local database file path
            s3_key: S3 key (defaults to just the filename)
            
        Returns:
            True if database was downloaded, False otherwise
        """
        if not s3_key:
            s3_key = Path(db_path).name
            
        return self.download_if_exists(s3_key, db_path)
    
    def sync_database_to_s3(self, db_path: str, s3_key: Optional[str] = None) -> bool:
        """Upload database to S3.
        
        Args:
            db_path: Local database file path
            s3_key: S3 key (defaults to just the filename)
            
        Returns:
            True if upload succeeded, False otherwise
        """
        if not s3_key:
            s3_key = Path(db_path).name
            
        return self.upload(db_path, s3_key)


# Global S3 storage instance
_s3_storage = None


def get_s3_storage() -> S3Storage:
    """Get or create global S3Storage instance."""
    global _s3_storage
    if _s3_storage is None:
        _s3_storage = S3Storage()
    return _s3_storage
