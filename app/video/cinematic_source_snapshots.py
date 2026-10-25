"""Private cinematic FFmpeg source snapshot leases and conservative POSIX recovery.

Draft helper proposal: advisory locks fence live source copies from cleanup.
Never interpret an unmarked or unsafe filesystem entry as a disposable snapshot.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import tempfile

try:
    import fcntl
except ImportError:  # Windows: no portable flock-compatible recovery.
    fcntl = None

_PREFIX = ".cinematic-source-snapshot-"
_MARKER = ".active.lock"


class PrivateSourceSnapshots:
    """A private temporary input directory with a live-process lease."""

    def __init__(self, parent: Path):
        self._temporary = tempfile.TemporaryDirectory(prefix=_PREFIX, dir=parent)
        self.name = self._temporary.name
        self._lease_fd: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            self._lease_fd = os.open(Path(self.name) / _MARKER, flags, 0o600)
            if fcntl is not None:
                fcntl.flock(self._lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.cleanup()
            raise

    def cleanup(self) -> None:
        if fcntl is None:
            # Windows cannot unlink an open file reliably; recovery is disabled.
            if self._lease_fd is not None:
                os.close(self._lease_fd)
                self._lease_fd = None
            self._temporary.cleanup()
            return
        try:
            # Keep the lease held throughout deletion; another startup skips us.
            self._temporary.cleanup()
        finally:
            if self._lease_fd is not None:
                os.close(self._lease_fd)
                self._lease_fd = None


def cleanup_abandoned_source_snapshots(asset_dir: Path) -> dict[str, int | bool]:
    """Delete only dead, private, app-marked POSIX snapshots.

    Never delete active locks, symlinks, world-readable directories, unmarked
    directories, or paths that cannot be inspected. Unsupported systems skip
    automatic recovery. This does not defend against malicious same-UID actors.
    """
    result: dict[str, int | bool] = {"removed": 0, "skipped": 0, "unsupported": False}
    if fcntl is None or not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        result["unsupported"] = True
        return result
    try:
        candidates = list(asset_dir.iterdir())
    except FileNotFoundError:
        return result
    for candidate in candidates:
        if not candidate.name.startswith(_PREFIX):
            continue
        directory_fd = None
        lease_fd = None
        try:
            dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory_fd = os.open(candidate, dir_flags)
            info = os.fstat(directory_fd)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                result["skipped"] += 1
                continue
            flags = os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            lease_fd = os.open(_MARKER, flags, dir_fd=directory_fd)
            marker = os.fstat(lease_fd)
            if (not stat.S_ISREG(marker.st_mode) or marker.st_uid != os.getuid()
                    or marker.st_mode & 0o077 or marker.st_nlink != 1):
                result["skipped"] += 1
                continue
            try:
                fcntl.flock(lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                result["skipped"] += 1
                continue
            # Reject renamed/replaced directory entries after taking the lease.
            current = os.lstat(candidate)
            if (not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
                result["skipped"] += 1
                continue
            shutil.rmtree(candidate)
            result["removed"] += 1
        except OSError:
            # Conservative: never delete an entry whose ownership/lease is unclear.
            result["skipped"] += 1
        finally:
            if lease_fd is not None:
                os.close(lease_fd)
            if directory_fd is not None:
                os.close(directory_fd)
    return result
