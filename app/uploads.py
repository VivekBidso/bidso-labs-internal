import re
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import settings

# Matches the frontend's own stated limits (DesignerStage1.jsx: "25 MB total",
# Manufacturer.jsx product photos) — enforced server-side too, not just in copy.
MAX_UPLOAD_BYTES = {
    "DESIGNER_STAGE_1": 25 * 1024 * 1024,
    "MANUFACTURER_REGISTRATION": 15 * 1024 * 1024,
}

# One stage per track today — Designer Stage 2 (CAD) isn't wired up server-side
# yet (DesignerStage2.jsx posts metadata only, no backend route exists for it).
TRACK_STAGE = {
    "DESIGNER": "DESIGNER_STAGE_1",
    "MANUFACTURER": "MANUFACTURER_REGISTRATION",
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(filename: str) -> str:
    name = filename.strip().replace("\\", "/").split("/")[-1] or "file"
    return _UNSAFE_FILENAME_CHARS.sub("_", name)[:200]


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def presign_upload(
    *, track: str, submission_id: str, stage: str, filename: str,
    content_type: str | None = None, expires_in: int = 900,
) -> dict:
    """Issue a presigned PUT URL for a file scoped to {track}/{submission_id}/{stage}/{key}.

    The caller (browser) uploads directly to object storage with this — the
    file never passes through this app server. Each key gets a random prefix
    so two files with the same name never collide or overwrite each other.

    Uses a presigned PUT, not a presigned POST: confirmed live against R2 that
    generate_presigned_post always fails there with
    "501 NotImplemented: Presigned post requests are not yet implemented" —
    R2's S3-compatible API never implemented POST Object, so no upload
    through that method could ever have succeeded. PUT is fully supported.
    Note this drops the server-enforced content-length-range condition that
    a POST policy could carry; max_bytes is still returned here for the
    frontend's own pre-upload size check.
    """
    safe_name = sanitize_filename(filename)
    key = f"{track}/{submission_id}/{stage}/{uuid.uuid4().hex}-{safe_name}"
    max_bytes = MAX_UPLOAD_BYTES.get(stage, 25 * 1024 * 1024)

    client = _r2_client()
    params = {"Bucket": settings.r2_bucket_name, "Key": key}
    if content_type:
        params["ContentType"] = content_type
    url = client.generate_presigned_url(
        ClientMethod="put_object",
        Params=params,
        ExpiresIn=expires_in,
    )
    return {"key": key, "upload_url": url, "content_type": content_type, "max_bytes": max_bytes}


def head_object(key: str) -> dict | None:
    """Confirms an object actually landed in R2 and returns its real size/content-type.

    Returns None if nothing exists at that key — the confirm step uses this to
    refuse to record an attachment for a key that was presigned but never
    actually uploaded (a dropped/failed browser upload).
    """
    client = _r2_client()
    try:
        resp = client.head_object(Bucket=settings.r2_bucket_name, Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return {
        "size_bytes": resp.get("ContentLength"),
        "content_type": resp.get("ContentType"),
    }
