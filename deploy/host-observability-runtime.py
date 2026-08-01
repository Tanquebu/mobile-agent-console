#!/usr/bin/env python3
import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOTLESS_UID_ENV = "MAC_HOST_OBSERVABILITY_ROOTLESS_UID"
ROOTFUL_BACKEND_UID = 10001


def parse_rootless_uid(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"{ROOTLESS_UID_ENV} must be a numeric host UID")
    uid = int(value)
    if uid < 1 or uid > 2**31 - 1:
        raise ValueError(f"{ROOTLESS_UID_ENV} is outside the supported range")
    return uid


def prepare_runtime(directory: Path, rootless_uid: int | None) -> None:
    directory.mkdir(mode=0o750, parents=False, exist_ok=True)
    current = directory.lstat()
    if not stat.S_ISDIR(current.st_mode) or directory.is_symlink():
        raise ValueError("host observability runtime path must be a real directory")
    # Revoca prima ogni accesso di gruppo; le ACL nominali desiderate vengono
    # poi ricreate da zero, così un vecchio UID rootless non resta autorizzato.
    os.chmod(directory, 0o700)

    setfacl = shutil.which("setfacl")
    if setfacl is None:
        raise RuntimeError("setfacl is required for host observability isolation")
    subprocess.run(
        [setfacl, "-b", "-k", str(directory)],
        check=True,
        shell=False,
        timeout=5,
    )
    backend_uids = {ROOTFUL_BACKEND_UID}
    if rootless_uid is not None:
        backend_uids.add(rootless_uid)
    acl_entries = ["g::---", "d:g::---"]
    for uid in sorted(backend_uids):
        acl_entries.extend((f"u:{uid}:r-x", f"d:u:{uid}:rw-"))
    subprocess.run(
        [
            setfacl,
            "-m",
            ",".join(acl_entries),
            str(directory),
        ],
        check=True,
        shell=False,
        timeout=5,
    )


def main() -> None:
    runtime_directory = Path(os.environ["XDG_RUNTIME_DIR"]) / "mobile-agent-console"
    prepare_runtime(
        runtime_directory,
        parse_rootless_uid(os.environ.get(ROOTLESS_UID_ENV)),
    )


if __name__ == "__main__":
    main()
