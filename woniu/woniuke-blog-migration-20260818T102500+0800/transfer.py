import os
from pathlib import Path

import paramiko


HOST = "152.136.161.128"
REMOTE_DIR = "/tmp/woniuke-blog-migration-20260818T102500+0800"
FILES = [
    "blog.sql.gz",
    "redis.rdb",
    "redis.conf",
    "blog-files.tar.gz",
    "manifest.env",
    "backup_started_at.txt",
    "SHA256SUMS",
]


def main():
    local_dir = Path(os.environ["BACKUP_LOCAL_ROOT"])
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username="ubuntu",
        password=os.environ["BACKUP_SSH_PASSWORD"],
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    sftp = client.open_sftp()
    try:
        for name in FILES:
            source = f"{REMOTE_DIR}/{name}"
            target = local_dir / name
            size = sftp.stat(source).st_size
            print(f"Downloading {name} ({size:,} bytes)", flush=True)
            sftp.get(source, str(target))
            print(f"Completed {name}", flush=True)
    finally:
        sftp.close()
        client.close()
    print("TRANSFER_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
