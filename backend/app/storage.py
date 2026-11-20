import socket
import struct
from functools import lru_cache

import boto3
from botocore.config import Config

from app.config import settings


@lru_cache
def s3():
    return boto3.client("s3", endpoint_url=settings().s3_endpoint,
                        config=Config(connect_timeout=3, read_timeout=15, retries={"max_attempts": 2}))


def put(key, content):
    config = settings()
    if config.s3_bucket:
        s3().put_object(Bucket=config.s3_bucket, Key=key, Body=content, ServerSideEncryption="AES256")
    else:
        path = config.local_objects / key
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)


def get(key):
    config = settings()
    if config.s3_bucket:
        response = s3().get_object(Bucket=config.s3_bucket, Key=key)
        with response["Body"] as body:
            return body.read(config.upload_bytes + 1)
    return (config.local_objects / key).read_bytes()


def remove(key):
    config = settings()
    if config.s3_bucket:
        s3().delete_object(Bucket=config.s3_bucket, Key=key)
    else:
        (config.local_objects / key).unlink(missing_ok=True)


def malware_check(content):
    if not settings().clamd_host:
        return
    with socket.create_connection((settings().clamd_host, 3310), timeout=10) as conn:
        conn.sendall(b"zINSTREAM\0")
        for offset in range(0, len(content), 65536):
            chunk = content[offset:offset + 65536]
            conn.sendall(struct.pack("!I", len(chunk)) + chunk)
        conn.sendall(b"\0" * 4)
        with conn.makefile("rb") as stream:
            result = stream.read(4096)
    if result.strip(b"\0\r\n") != b"stream: OK":
        raise ValueError("Upload did not pass malware scanning")
