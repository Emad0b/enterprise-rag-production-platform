import os
from pathlib import Path
from .config import RUNTIME


def client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        region_name=os.getenv("S3_REGION", "us-east-1"),
    )


def put(key, raw, media_type):
    if os.getenv("S3_BUCKET"):
        c = client()
        bucket = os.environ["S3_BUCKET"]
        try:
            c.head_bucket(Bucket=bucket)
        except c.exceptions.ClientError as error:
            if str(error.response["Error"]["Code"]) not in ("404", "NoSuchBucket"):
                raise
            c.create_bucket(Bucket=bucket)
        c.put_object(Bucket=bucket, Key=key, Body=raw, ContentType=media_type)
    else:
        directory = RUNTIME / "objects"
        directory.mkdir(exist_ok=True)
        (directory / key).write_bytes(raw)


def get(key):
    if not key or Path(key).name != key:
        raise ValueError("Invalid object key")
    if os.getenv("S3_BUCKET"):
        return (
            client().get_object(Bucket=os.environ["S3_BUCKET"], Key=key)["Body"].read()
        )
    return (RUNTIME / "objects" / key).read_bytes()
