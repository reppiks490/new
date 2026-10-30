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
# Persistent parent-scoped mutex; unlike per-snapshot markers, this is
# acquired BEFORE a new recoverable snapshot directory becomes visible.
_FENCE = ".cinematic-source-snapshots.guard"


def _open_recovery_fence(parent: Path, *, blocking: bool) -> int | None:
    """Acquire the shared creator/reaper fence; None means busy/non-POSIX.

    The guard is never unlinked: unlinking would allow concurrent processes
    to lock different inodes under the same pathname. Suspicious pre-existing
    entries fail closed instead of being replaced or followed.
    """
    if fcntl is None:
        return None
    if not hasattr(os, "O_NOFOLLOW"):
        raise OSError("Safe no-follow source snapshot fence is unavailable")
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(parent / _FENCE, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise OSError("Unsafe source snapshot recovery fence")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            os.close(fd)
            return None
        return fd
    except BaseException:
        os.close(fd)
        raise


class PrivateSourceSnapshots:
    """A private temporary input directory with a live-process lease."""

    def __init__(self, parent: Path):
        self._lease_fd: int | None = None
        # Fence both directory creation and marker lease acquisition. Startup
        # cleanup takes the same guard before inspecting any candidate.
        guard_fd = _open_recovery_fence(parent, blocking=True)
        try:
            self._temporary = tempfile.TemporaryDirectory(prefix=_PREFIX, dir=parent)
            self.name = self._temporary.name
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
        finally:
            if guard_fd is not None:
                os.close(guard_fd)

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


def _cleanup_abandoned_source_snapshots_unfenced(asset_dir: Path) -> dict[str, int | bool]:
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


def cleanup_abandoned_source_snapshots(asset_dir: Path) -> dict[str, int | bool]:
    """Recover abandoned snapshots without racing directory/lease creation.

    A busy guard means another process is creating a live snapshot or already
    recovering. Skip this pass; the next startup can retry orphan cleanup.
    """
    result: dict[str, int | bool] = {"removed": 0, "skipped": 0, "unsupported": False}
    if fcntl is None or not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        result["unsupported"] = True
        return result
    try:
        guard_fd = _open_recovery_fence(asset_dir, blocking=False)
    except FileNotFoundError:
        return result
    except OSError:
        result["skipped"] += 1
        return result
    if guard_fd is None:
        result["skipped"] += 1
        return result
    try:
        return _cleanup_abandoned_source_snapshots_unfenced(asset_dir)
    finally:
        os.close(guard_fd)
