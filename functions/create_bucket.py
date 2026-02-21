from google.cloud import storage
import os

os.environ['GCLOUD_PROJECT'] = 'lofa-43d38'

def create_bucket():
    # Newer Firebase projects use .firebasestorage.app as the default bucket name.
    bucket_name = 'lofa-43d38.firebasestorage.app'
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        if bucket.exists():
            print(f"Bucket {bucket.name} already exists.")
        else:
            bucket.location = 'US'
            bucket = storage_client.create_bucket(bucket_name)
            print(f"Bucket {bucket.name} created.")
            
        # Configure CORS for the bucket
        cors_config = [
            {
                "origin": ["*"],
                "responseHeader": ["Content-Type", "x-goog-resumable"],
                "method": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "maxAgeSeconds": 3600
            }
        ]
        bucket.cors = cors_config
        bucket.patch()
        print(f"Set CORS for bucket {bucket.name}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    create_bucket()
