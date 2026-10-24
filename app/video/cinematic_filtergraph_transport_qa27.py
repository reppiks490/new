"""Opt-in private FFmpeg filtergraph-script transport for many-shot masters.

This module is intentionally NOT wired into master assembly. The cinematic
service owner must review and integrate it before QA26's E2BIG defect is fixed.
No media, model inference, network, or subprocess execution occurs here.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from typing import Iterator, Sequence


@contextmanager
def private_filtergraph_script_command(
    command: Sequence[str], *, directory: str | os.PathLike[str],
) -> Iterator[list[str]]:
    """Replace a single FFmpeg ``-filter_complex`` argument with a 0600 script.

    Caller must run FFmpeg *inside* this context; the script is unlinked on
    success, error, cancellation, or process-launch failure. Use a trusted,
    private local directory on the same owner PC. Never log script contents.
    The caller remains responsible for subprocess timeouts, cancellation,
    output cleanup, and detecting FFmpeg's supported script-option syntax.
    """
    argv = list(command)
    if not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError('FFmpeg arguments must be nonempty strings')
    positions = [i for i, arg in enumerate(argv) if arg == '-filter_complex']
    if len(positions) != 1:
        raise ValueError('Expected exactly one FFmpeg filtergraph argument')
    index = positions[0]
    if index + 1 >= len(argv) or not argv[index + 1]:
        raise ValueError('FFmpeg filtergraph is missing')
    if '-filter_complex_script' in argv:
        raise ValueError('Command already contains a filtergraph script')
    graph = argv[index + 1]
    folder = Path(directory)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('Trusted filtergraph directory must exist and not be a symlink')

    fd, path = tempfile.mkstemp(prefix='.cinematic-filter-', suffix='.ffgraph', dir=folder)
    try:
        # mkstemp is O_EXCL and mode 0600; explicitly enforce mode on POSIX.
        if os.name == 'posix':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as output:
            fd = -1
            output.write(graph)
            output.flush()
            os.fsync(output.fileno())
        argv[index:index + 2] = ['-filter_complex_script', path]
        yield argv
    finally:
        if fd != -1:
            os.close(fd)
        Path(path).unlink(missing_ok=True)
