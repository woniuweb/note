import base64
from pathlib import Path

import paramiko


HOST = "152.136.161.128"
REMOTE_DIR = "/tmp/woniuke-blog-migration-20260818T102500+0800"
KEY = "MjAwMDgyNkxpQA=="
FILES = [
    "blog.sql.gz",
    "redis.rdb",
    "redis.conf",
    "blog-files.tar.gz",
    "manifest.env",
    "backup_started_at.txt",
    "SHA256SUMS",
]
LOCAL_DIR = Path(r"D:\obsidian\woniu\woniuke-blog-migration-20260818T102500+0800")


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username="ubuntu",
        password=base64.b64decode(KEY).decode(),
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    sftp = client.open_sftp()
    try:
        for name in ["blog-files.tar.gz"]:
            source = f"{REMOTE_DIR}/{name}"
            target = LOCAL_DIR / name
            size = sftp.stat(source).st_size
            print(f"Downloading {name} ({size:,} bytes)", flush=True)
            sftp.get(source, str(target), prefetch=True, max_concurrent_prefetch_requests=64)
            print(f"Completed {name}", flush=True)
    finally:
        sftp.close()
        client.close()


if __name__ == "__main__":
    main()
