"""Bounded UTF-8 editing, descriptor-based paths and optimistic concurrency."""

import hashlib
import os
import stat
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

MAX_MARKDOWN_BYTES = 256 * 1024
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
_write_lock = threading.Lock()


@contextmanager
def _parent(path: Path):
    # The caller resolves/authorizes the canonical path. Do not follow a
    # directory replaced by a symlink between authorization and open.
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _read(parent: int, name: str) -> tuple[bytes, os.stat_result, str]:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise HTTPException(400, "Only regular Markdown files without hard links are editable")
        raw = stream.read(MAX_MARKDOWN_BYTES + 1)
        if len(raw) > MAX_MARKDOWN_BYTES:
            raise HTTPException(413, "Markdown file exceeds 256 KiB")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "Markdown must be UTF-8 text") from exc
        if b"\0" in raw:
            raise HTTPException(400, "Markdown must be UTF-8 text")
        version = f"{info.st_dev}:{info.st_ino}:{info.st_mtime_ns}:{info.st_ctime_ns}:".encode()
        return raw, info, hashlib.sha256(version + raw).hexdigest()


def markdown_file(path: Path, content: str | None = None, revision: str | None = None) -> dict:
    if path.suffix.lower() not in MARKDOWN_EXTENSIONS:
        raise HTTPException(400, "Only .md and .markdown files are editable")
    try:
        encoded = content.encode("utf-8") if content is not None else None
    except UnicodeEncodeError as exc:
        raise HTTPException(400, "Markdown must be UTF-8 text") from exc
    if encoded is not None and (len(encoded) > MAX_MARKDOWN_BYTES or b"\0" in encoded):
        raise HTTPException(400, "Markdown must be UTF-8 text up to 256 KiB")
    try:
        with _write_lock, _parent(path) as parent:
            raw, info, current_revision = _read(parent, path.name)
            if encoded is not None:
                if revision != current_revision:
                    raise HTTPException(409, "File changed on disk; reopen it before saving")
                temporary = f".mac-markdown-{uuid.uuid4().hex}"
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(encoded)
                        stream.flush()
                        os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode) & 0o777)
                        os.fsync(stream.fileno())
                    if _read(parent, path.name)[2] != current_revision:
                        raise HTTPException(409, "File changed on disk; reopen it before saving")
                    os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
                    os.fsync(parent)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=parent)
                    except FileNotFoundError:
                        pass
                raw, _, current_revision = _read(parent, path.name)
            return {"path": str(path), "content": raw.decode("utf-8"), "revision": current_revision}
    except FileNotFoundError as exc:
        raise HTTPException(404, "File not found") from exc
    except OSError as exc:
        raise HTTPException(400, "Markdown file cannot be accessed safely or is read-only") from exc
