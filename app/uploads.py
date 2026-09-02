import boto3
from botocore.config import Config

from app.config import settings


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def presign_upload(*, track: str, reference_number: str, stage: str, filename: str, expires_in: int = 900) -> dict:
    """Issue a presigned POST for a file scoped to {track}/{reference_number}/{stage}/{filename}.

    The caller (browser) uploads directly to object storage with this — the
    file never passes through this app server.
    """
    key = f"{track}/{reference_number}/{stage}/{filename}"
    client = _r2_client()
    presigned = client.generate_presigned_post(
        Bucket=settings.r2_bucket_name,
        Key=key,
        ExpiresIn=expires_in,
    )
    return {"key": key, "upload": presigned}
