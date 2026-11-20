"""Exercise configured object storage and the malware scanner before routing traffic."""

import argparse
from uuid import uuid4

from app.config import settings
from app.storage import get, malware_check, put, remove


def probe(verify_detection):
    config = settings()
    if not config.s3_bucket or not config.clamd_host:
        raise ValueError("Configure the S3 bucket and ClamAV before running this probe")

    key = "release-health/" + str(uuid4())
    clean = b"ResearchPilot storage and scanner readiness fixture.\n"
    put(key, clean)
    try:
        if get(key) != clean:
            raise RuntimeError("Object storage returned different content")
    finally:
        remove(key)
    malware_check(clean)
    if verify_detection:
        # The EICAR string is an inert antivirus test fixture.
        marker = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}" + b"$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
        try:
            malware_check(marker)
        except ValueError as exc:
            if "FOUND" not in str(exc):
                raise
        else:
            raise RuntimeError("The scanner accepted the EICAR test fixture")
    print("Object storage round trip and ClamAV scan passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-detection", action="store_true", help="Verify the scanner rejects the EICAR test fixture")
    probe(parser.parse_args().verify_detection)
