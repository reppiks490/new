"""Read-only local media toolchain preflight for a trusted Character3D operator.

This deliberately does not import server state, open media, create directories,
write to the workspace, run an encode, load models or contact any provider.
It is NOT a release or owner-PC performance certification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess


_NOT_VERIFIED = [
    "MODEL_INFERENCE_NOT_TESTED",
    "RENDER_OUTPUT_NOT_TESTED",
    "WINDOWS_WSL2_PERFORMANCE_NOT_TESTED",
    "PHYSICAL_MOBILE_PLAYBACK_NOT_TESTED",
    "MULTIPROCESS_QUEUE_NOT_SAFE",
    "SOURCE_AUDIO_POLICY_NOT_RESOLVED",
    "FOUR_K_DELIVERY_NOT_TESTED",
]


def _check(name: str, status: str, code: str) -> dict[str, str]:
    return {"name": name, "status": status, "code": code}


def _resolve_executable(candidate: str) -> str | None:
    try:
        return shutil.which(candidate)
    except (OSError, ValueError, TypeError):
        return None


def _run_probe(executable: str, args: list[str]) -> subprocess.CompletedProcess | None:
    # No shell, no input, no media paths, no logs of local stdout/stderr.
    try:
        result = subprocess.run(
            [executable, *args], capture_output=True, text=True,
            timeout=8, check=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return result if result.returncode == 0 else None


def _has_libx264_encoder(output: str) -> bool:
    """Match an actual FFmpeg encoder listing, not a banner/help mention."""
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and re.fullmatch(r"[A-Z.]{6}", fields[0]):
            if fields[1] == "libx264":
                return True
    return False


def audit_local_media_runtime(
    *,
    workspace: str | Path | None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    min_free_gib: int = 10,
) -> dict:
    """Report only local metadata and toolchain probes; never echo paths.

    Passing means only that these four narrow checks passed *at this instant*.
    It does not prove the directory is writable or that any video can render.
    Call only from a trusted local CLI; executable selection uses the local PATH.
    """
    if type(min_free_gib) is not int or min_free_gib < 1:
        raise ValueError("min_free_gib must be a positive integer")

    checks: list[dict[str, str]] = []
    ffmpeg_bin = _resolve_executable(ffmpeg)
    ffmpeg_version = _run_probe(ffmpeg_bin, ["-version"]) if ffmpeg_bin else None
    if ffmpeg_version is None:
        checks.append(_check("ffmpeg_binary", "blocked", "FFMPEG_UNRESPONSIVE"))
        checks.append(_check("h264_encoder", "not_checked", "FFMPEG_NOT_VERIFIED"))
    else:
        checks.append(_check("ffmpeg_binary", "passed", "FFMPEG_RESPONSIVE"))
        encoders = _run_probe(ffmpeg_bin, ["-hide_banner", "-encoders"])
        if encoders is not None and _has_libx264_encoder(encoders.stdout):
            checks.append(_check("h264_encoder", "passed", "LIBX264_AVAILABLE"))
        else:
            checks.append(_check("h264_encoder", "blocked", "LIBX264_UNAVAILABLE"))

    ffprobe_bin = _resolve_executable(ffprobe)
    ffprobe_version = _run_probe(ffprobe_bin, ["-version"]) if ffprobe_bin else None
    if ffprobe_version is None:
        checks.append(_check("ffprobe_binary", "blocked", "FFPROBE_UNRESPONSIVE"))
    else:
        checks.append(_check("ffprobe_binary", "passed", "FFPROBE_RESPONSIVE"))

    if workspace is None:
        checks.append(_check("workspace_disk", "not_checked", "WORKSPACE_NOT_SUPPLIED"))
    else:
        try:
            path = Path(workspace)
            if not path.is_dir():
                checks.append(_check("workspace_disk", "blocked", "WORKSPACE_NOT_DIRECTORY"))
            else:
                free = shutil.disk_usage(path).free
                if free >= min_free_gib * 1024 ** 3:
                    checks.append(_check(
                        "workspace_disk", "passed", "WORKSPACE_FREE_SPACE_ABOVE_FLOOR",
                    ))
                else:
                    checks.append(_check(
                        "workspace_disk", "blocked", "WORKSPACE_FREE_SPACE_BELOW_FLOOR",
                    ))
        except (OSError, ValueError, TypeError):
            checks.append(_check("workspace_disk", "blocked", "WORKSPACE_DISK_UNAVAILABLE"))

    # Stable ordering is part of the small public report contract.
    by_name = {item["name"]: item for item in checks}
    ordered = [
        by_name[name] for name in (
            "ffmpeg_binary", "ffprobe_binary", "h264_encoder", "workspace_disk",
        )
    ]
    return {
        "schema_version": 1,
        "scope": "read_only_local_media_preflight",
        "checks": ordered,
        "limited_ready": all(item["status"] == "passed" for item in ordered),
        "release_ready": False,
        "not_verified": list(_NOT_VERIFIED),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only local Character3D FFmpeg/FFprobe/disk check; no rendering."
    )
    parser.add_argument("--workspace", type=Path, help="Existing trusted local workspace")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Trusted FFmpeg executable")
    parser.add_argument("--ffprobe", default="ffprobe", help="Trusted FFprobe executable")
    parser.add_argument("--min-free-gib", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        report = audit_local_media_runtime(
            workspace=args.workspace, ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe, min_free_gib=args.min_free_gib,
        )
    except ValueError:
        parser.error("--min-free-gib must be a positive integer")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["limited_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
