"""Deterministic genuine-FFmpeg test for in-flight cinematic source provenance.

Only the scheduling seam is instrumented: a synthetic source is replaced
AFTER the service fingerprints it but BEFORE the real FFmpeg subprocess
opens it. Both source generations and the master use actual libx264, ffprobe
and full decoding. This is an isolated QA contract, not an exploit script,
owner-footage test, or proposed change to lead-owned production files.
"""
from __future__ import annotations

import hashlib
import os
import stat
import shutil
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.video import cinematic_models as models
from app.video import cinematic_service as service
from app.video import storage
from app.video.cinematic_requests import AssembleMasterRequest


def real_command(*args: str) -> bytes:
    return subprocess.run(args, check=True, capture_output=True, timeout=120).stdout


def encode_synthetic(path: Path, color: str) -> None:
    real_command(
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=10",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(path),
    )


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class InFlightSourceProvenance(unittest.TestCase):
    def make_ready_project(self):
        created = service.create_project(models.ProjectCreateRequest(
            title="Synthetic in-flight provenance QA",
            master_prompt="SYNTHETIC_PRIVATE_INFLIGHT_CANARY",
            target_duration_seconds=10, delivery_fps=24,
            delivery_resolution="480p", aspect_ratio="16:9",
            reference_image_ids=[],
        ))
        scene_id, shot_id, asset_id = uuid4().hex, uuid4().hex, uuid4().hex
        shot = models.CinematicShot(
            shot_id=shot_id, ordinal=1, title="Synthetic source",
            prompt="Solid synthetic color", duration_seconds=10,
        )
        scene = models.CinematicScene(
            scene_id=scene_id, ordinal=1, title="Synthetic scene",
            target_duration_seconds=10, shots=[shot],
        )
        project = service.update_project(
            created.id,
            models.ProjectUpdateRequest(expected_revision=1, scenes=[scene]),
        )
        source = storage.video_asset_path(asset_id, "mp4")
        encode_synthetic(source, "red")
        render = storage.put_video_record("video_job", {
            "status": "succeeded", "stage": "Ready", "progress": 100,
            "project_id": project.id, "scene_id": scene_id,
            "shot_id": shot_id, "project_revision": 2,
            "asset_id": asset_id,
            "asset_url": f"/api/video/assets/{asset_id}.mp4",
        })
        project = service.update_project(
            project.id, models.ProjectUpdateRequest(
                expected_revision=2,
                scenes=[scene.model_copy(update={"shots": [
                    shot.model_copy(update={
                        "latest_job_id": render["id"],
                        "latest_rendered_project_revision": 2,
                    }),
                ]})],
            ),
        )
        self.assertEqual(project.revision, 3)
        self.assertTrue(service.project_render_status(project.id)["ready_for_assembly"])
        return project, source

    def assert_real_media(self, record: dict, expected_color: str):
        output = storage.video_asset_path(record["asset_id"], "mp4")
        self.assertEqual(sha256(output), record["sha256"])
        info = json.loads(real_command(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,nb_frames",
            "-of", "json", str(output),
        ))
        video = info["streams"][0]
        self.assertEqual(video["codec_name"], "h264")
        self.assertEqual((video["width"], video["height"]), (854, 480))
        self.assertEqual(int(video["nb_frames"]), 240)
        real_command(
            "ffmpeg", "-nostdin", "-v", "error", "-xerror",
            "-i", str(output), "-an", "-f", "null", "-",
        )
        pixel = real_command(
            "ffmpeg", "-nostdin", "-v", "error", "-ss", "5",
            "-i", str(output), "-vf", "scale=1:1", "-frames:v", "1",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        )
        self.assertEqual(len(pixel), 3)
        index = {"red": 0, "green": 1, "blue": 2}[expected_color]
        self.assertGreater(pixel[index], max(
            value for i, value in enumerate(pixel) if i != index
        ) + 65)

    def test_unchanged_source_is_correctly_hashed_and_cached(self):
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        first = service.assemble_project_master(project.id, request)
        self.assertEqual(first["source_asset_hashes"], [sha256(source)])
        self.assertTrue(first["actual_video_probe_verified"])
        self.assert_real_media(first, "red")
        second = service.assemble_project_master(project.id, request)
        self.assertEqual(second["id"], first["id"])

    def test_source_replaced_between_fingerprint_and_real_ffmpeg_must_not_publish_stale_lineage(self):
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        preflight_sha = sha256(source)
        original_runner = service._run_master_ffmpeg
        mutations = []

        def replace_then_run_actual_ffmpeg(command, **kwargs):
            # Deterministic scheduling seam only; real FFmpeg still encodes,
            # assembles, probes, and fully decodes every synthetic MP4.
            encode_synthetic(source, "blue")
            mutations.append(sha256(source))
            return original_runner(command, **kwargs)

        with patch.object(service, "_run_master_ffmpeg",
                          side_effect=replace_then_run_actual_ffmpeg):
            try:
                master = service.assemble_project_master(project.id, request)
            except service.MasterAssemblyNotReady:
                # An explicit fail-closed rejection is also acceptable.
                self.assertEqual(len(mutations), 1)
                self.assertNotEqual(mutations[0], preflight_sha)
                self.assertFalse([
                    row for row in storage.list_video_records("video_master")
                    if row.get("project_id") == project.id
                    and row.get("status") == "ready"
                ])
                return

        self.assertEqual(len(mutations), 1, "Mutation hook must execute once")
        self.assertNotEqual(mutations[0], preflight_sha)
        self.assert_real_media(master, "blue")
        # RED on the current service: fingerprint/source hashes are captured
        # before FFmpeg opens the mutated source. A ready master must never
        # attest the OLD red bytes while containing NEW blue decoded frames.
        self.assertEqual(
            master["source_asset_hashes"], [sha256(source)],
            "Published source SHA-256 lineage must match bytes actually assembled",
        )
        self.assertEqual(
            service.assemble_project_master(project.id, request)["id"],
            master["id"],
            "Corrected source fingerprint must remain a stable cache identity",
        )


    def test_mutate_and_revert_during_real_ffmpeg_must_not_publish_false_lineage(self):
        """A matching post-encode SHA alone cannot attest the encoded input bytes."""
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        original_bytes = source.read_bytes()
        original_sha = sha256(source)
        original_runner = service._run_master_ffmpeg
        mutation_hashes = []

        def encode_changed_bytes_then_restore(command, **kwargs):
            # Only instrument FFmpeg's scheduling seam; the actual FFmpeg
            # encoder runs to completion against synthetic BLUE footage.
            # Restore the exact original RED bytes before service post-hash.
            encode_synthetic(source, "blue")
            mutation_hashes.append(sha256(source))
            try:
                return original_runner(command, **kwargs)
            finally:
                source.write_bytes(original_bytes)

        with patch.object(service, "_run_master_ffmpeg",
                          side_effect=encode_changed_bytes_then_restore):
            try:
                master = service.assemble_project_master(project.id, request)
            except service.MasterAssemblyNotReady:
                # Immutable snapshots/locking or explicit rejection are valid.
                self.assertEqual(len(mutation_hashes), 1)
                self.assertNotEqual(mutation_hashes[0], original_sha)
                self.assertEqual(sha256(source), original_sha)
                self.assertFalse([
                    row for row in storage.list_video_records("video_master")
                    if row.get("project_id") == project.id
                    and row.get("status") == "ready"
                ])
                return

        self.assertEqual(len(mutation_hashes), 1, "Real FFmpeg hook must run once")
        self.assertNotEqual(mutation_hashes[0], original_sha)
        self.assertEqual(sha256(source), original_sha)
        self.assertEqual(master["source_asset_hashes"], [original_sha])
        # The persisted RED lineage and cache fingerprint are false when
        # the real master actually decodes BLUE. This must reject or produce
        # a master that matches the attested source bytes.
        try:
            self.assert_real_media(master, "red")
        except AssertionError:
            # Establish the actual alternate color with full decode before
            # reporting the provenance violation; do not mask broken media.
            self.assert_real_media(master, "blue")
            self.fail(
                "Ready master decodes BLUE while source SHA attests restored RED; "
                "post-FFmpeg source rehash alone cannot prove input provenance"
            )


    def test_private_staged_mp4_mode_is_0600_with_standard_umask(self):
        """Genuine FFmpeg input copies must remain owner-only if parent perms drift.

        The 0700 staging directory already prevents other users from entering,
        but copied footage must not inherit a 0644 file mode from umask 022.
        The test records permissions while FFmpeg still owns the private copy.
        """
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        original_runner = service._run_master_ffmpeg
        observed = []

        def encode_and_capture_private_input_mode(command, **kwargs):
            staged = [
                Path(command[i + 1])
                for i, arg in enumerate(command[:-1]) if arg == "-i"
            ]
            self.assertEqual(len(staged), 1)
            self.assertNotEqual(staged[0], source)
            observed.append(stat.S_IMODE(staged[0].stat().st_mode))
            return original_runner(command, **kwargs)

        old_umask = os.umask(0o022)
        try:
            with patch.object(service, "_run_master_ffmpeg",
                              side_effect=encode_and_capture_private_input_mode):
                master = service.assemble_project_master(project.id, request)
        finally:
            os.umask(old_umask)
        self.assert_real_media(master, "red")
        self.assertEqual(observed, [0o600],
                         "Private source MP4 was staged with group/other-readable mode")

    def test_ffmpeg_failure_discards_private_input_snapshots(self):
        """A failed encode must not leave staged copies or publish a master."""
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        ffmpeg_inputs = []

        def synthetic_ffmpeg_failure(command, **kwargs):
            ffmpeg_inputs.extend(
                Path(command[i + 1])
                for i, arg in enumerate(command[:-1]) if arg == "-i"
            )
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

        with patch.object(service, "_run_master_ffmpeg",
                          side_effect=synthetic_ffmpeg_failure):
            with self.assertRaisesRegex(RuntimeError, "FFmpeg master assembly failed"):
                service.assemble_project_master(project.id, request)
        self.assertEqual(len(ffmpeg_inputs), 1)
        self.assertNotEqual(ffmpeg_inputs[0], source,
                            "FFmpeg must read a private verified snapshot, not mutable source")
        self.assertFalse(ffmpeg_inputs[0].exists(),
                         "Failed assembly must remove staged input bytes")
        self.assertFalse(ffmpeg_inputs[0].parent.exists(),
                         "Failed assembly must remove the private snapshot directory")
        self.assertFalse([
            row for row in storage.list_video_records("video_master")
            if row.get("project_id") == project.id and row.get("status") == "ready"
        ])




    @unittest.skipUnless(hasattr(os, "fork"), "POSIX-only isolated worker crash QA")
    def test_abrupt_worker_exit_requires_startup_snapshot_orphan_recovery(self):
        """A killed worker must not retain private copied footage after recovery.

        This is intentionally test-first: TemporaryDirectory finally handlers
        cannot execute after os._exit/SIGKILL. The child only handles disposable
        synthetic media; the parent cleans its fixture even when assertion fails.
        """
        from app.video.cinematic_assembly_jobs import recover_assembly_queue

        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        asset_dir = source.parent
        prefix = ".cinematic-source-snapshot-"
        before = {p.name for p in asset_dir.glob(prefix + "*")}
        pid = os.fork()
        if pid == 0:
            def terminate_after_staging(command, **kwargs):
                try:
                    inputs = [
                        Path(command[i + 1])
                        for i, arg in enumerate(command[:-1]) if arg == "-i"
                    ]
                    if len(inputs) != 1 or inputs[0] == source:
                        os._exit(82)
                    if sha256(inputs[0]) != sha256(source):
                        os._exit(82)
                    # Prove the staged copy contains genuinely decodable
                    # H.264 bytes before simulating an abrupt worker death.
                    real_command(
                        "ffmpeg", "-nostdin", "-v", "error", "-xerror",
                        "-i", str(inputs[0]), "-an", "-f", "null", "-",
                    )
                    os._exit(83)
                except BaseException:
                    os._exit(82)

            with patch.object(service, "_run_master_ffmpeg",
                              side_effect=terminate_after_staging):
                service.assemble_project_master(project.id, request)
            os._exit(82)

        _, status = os.waitpid(pid, 0)
        orphan_dirs = [
            p for p in asset_dir.glob(prefix + "*")
            if p.name not in before and p.is_dir()
        ]
        try:
            self.assertTrue(os.WIFEXITED(status), "Synthetic worker must exit cleanly")
            self.assertEqual(os.WEXITSTATUS(status), 83,
                             "Worker must exit only after real source-snapshot decode")
            self.assertEqual(len(orphan_dirs), 1,
                             "The test must demonstrate an abandoned private source copy")
            self.assertEqual(
                len(list(orphan_dirs[0].glob("*.mp4"))), 1,
                "Abandoned directory must contain one copied synthetic H.264 MP4",
            )
            # This is the same queue-recovery hook used at application startup.
            recover_assembly_queue()
            self.assertFalse(
                orphan_dirs[0].exists(),
                "Startup recovery left an orphan private source snapshot after "
                "abrupt worker termination; disk/privacy cleanup is missing",
            )
        finally:
            # Do not retain even synthetic test footage in the ephemeral CI image.
            for orphan in orphan_dirs:
                shutil.rmtree(orphan, ignore_errors=True)



    @unittest.skipUnless(hasattr(os, "fork"), "POSIX snapshot lease gate")
    def test_startup_recovery_must_not_remove_live_ffmpeg_input_snapshot(self):
        """A second startup cannot delete inputs held by an active encoder."""
        from app.video.cinematic_assembly_jobs import recover_assembly_queue

        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        original_runner = service._run_master_ffmpeg
        staged_paths = []
        before = {p.name for p in source.parent.glob(".cinematic-source-snapshot-*")}

        def verify_live_snapshot_then_encode(command, **kwargs):
            staged_paths.extend(
                Path(command[i + 1])
                for i, arg in enumerate(command[:-1]) if arg == "-i"
            )
            self.assertEqual(len(staged_paths), 1)
            self.assertNotEqual(staged_paths[0], source)
            self.assertEqual(sha256(staged_paths[0]), sha256(source))
            # Simulates another API process's startup recovery while the
            # actual FFmpeg worker still owns its verified private copy.
            recover_assembly_queue()
            self.assertTrue(
                staged_paths[0].is_file(),
                "Recovery deleted an active FFmpeg source snapshot",
            )
            real_command(
                "ffmpeg", "-nostdin", "-v", "error", "-xerror",
                "-i", str(staged_paths[0]), "-an", "-f", "null", "-",
            )
            return original_runner(command, **kwargs)

        with patch.object(service, "_run_master_ffmpeg",
                          side_effect=verify_live_snapshot_then_encode):
            master = service.assemble_project_master(project.id, request)
        self.assert_real_media(master, "red")
        self.assertEqual(len(staged_paths), 1)
        self.assertFalse(staged_paths[0].exists())
        self.assertEqual(
            {p.name for p in source.parent.glob(".cinematic-source-snapshot-*")},
            before,
            "A normally completed worker must remove its private snapshot",
        )


    @unittest.skipUnless(hasattr(os, "fork"), "POSIX filesystem safety gate")
    def test_recovery_skips_unmarked_and_symlinked_private_paths(self):
        """Startup cleanup must not traverse lookalike or linked paths."""
        from app.video.cinematic_assembly_jobs import recover_assembly_queue

        project, source = self.make_ready_project()
        root = source.parent
        unmarked = root / (".cinematic-source-snapshot-" + uuid4().hex)
        linked = root / (".cinematic-source-snapshot-" + uuid4().hex)
        unmarked.mkdir(mode=0o700)
        try:
            (unmarked / "synthetic-sentinel").write_text("NO_PRIVATE_MEDIA")
            linked.symlink_to(unmarked, target_is_directory=True)
            recover_assembly_queue()
            self.assertTrue(unmarked.is_dir())
            self.assertEqual(
                (unmarked / "synthetic-sentinel").read_text(), "NO_PRIVATE_MEDIA",
            )
            self.assertTrue(linked.is_symlink())
        finally:
            if linked.is_symlink():
                linked.unlink()
            shutil.rmtree(unmarked, ignore_errors=True)


    @unittest.skipUnless(os.name == "posix", "POSIX flock startup race regression")
    def test_recovery_cannot_delete_snapshot_during_lease_initialization(self):
        """A just-created marker is not proof that its worker has acquired a lease.

        Reproduce the precise ordering without sleeping or requiring owner
        footage: pause at the constructor's first flock, run real startup
        cleanup against the visible marker, then let construction proceed.
        A valid live snapshot must survive until its creator releases it.
        """
        from app.video import cinematic_source_snapshots as snapshot_module

        if snapshot_module.fcntl is None or not getattr(
            shutil.rmtree, "avoids_symlink_attacks", False
        ):
            self.skipTest("Safe POSIX snapshot recovery unavailable")

        _, source = self.make_ready_project()
        original_flock = snapshot_module.fcntl.flock
        observed_recovery = []

        def run_recovery_before_first_lease_lock(fd, operation):
            if not observed_recovery:
                # Set the guard before cleanup invokes flock itself, so its
                # nested lock attempt uses the original function directly.
                observed_recovery.append(None)
                # The lease marker already exists but the worker has not yet
                # acquired its advisory lock. Exercise the REAL cleanup code.
                observed_recovery[0] = (
                    snapshot_module.cleanup_abandoned_source_snapshots(source.parent)
                )
            return original_flock(fd, operation)

        with patch.object(
            snapshot_module.fcntl, "flock",
            side_effect=run_recovery_before_first_lease_lock,
        ):
            live = snapshot_module.PrivateSourceSnapshots(source.parent)
        try:
            self.assertEqual(len(observed_recovery), 1)
            self.assertEqual(
                observed_recovery[0]["removed"], 0,
                "Startup recovery removed a live worker's source snapshot "
                "between creation of .active.lock and acquisition of flock",
            )
            self.assertTrue(
                Path(live.name).is_dir(),
                "Worker acquired a lease on a snapshot directory already removed",
            )
            staged = Path(live.name) / "synthetic.mp4"
            shutil.copyfile(source, staged)
            self.assertEqual(sha256(staged), sha256(source))
            real_command(
                "ffmpeg", "-nostdin", "-v", "error", "-xerror",
                "-i", str(staged), "-an", "-f", "null", "-",
            )
        finally:
            live.cleanup()


    @unittest.skipUnless(os.name == "posix", "POSIX snapshot lease creation race")
    def test_recovery_at_marker_open_must_not_delete_initializing_source(self):
        """Startup recovery must not unlink an unleased but live source directory.

        Trigger recovery immediately after the real .active.lock file is opened
        and before its creator calls flock. Unlike a first-flock hook, this
        remains a valid interleaving even if construction adds a parent fence.
        """
        from app.video import cinematic_source_snapshots as snapshot_module

        if snapshot_module.fcntl is None or not getattr(
            shutil.rmtree, "avoids_symlink_attacks", False
        ):
            self.skipTest("Safe POSIX snapshot recovery unavailable")

        _, source = self.make_ready_project()
        original_open = snapshot_module.os.open
        observed = []

        def recover_after_marker_open(path, flags, mode=0o777, *, dir_fd=None):
            fd = original_open(path, flags, mode, dir_fd=dir_fd)
            if Path(os.fspath(path)).name == ".active.lock" and not observed:
                # Guard first: cleanup itself opens files using os.open.
                observed.append(None)
                observed[0] = snapshot_module.cleanup_abandoned_source_snapshots(
                    source.parent
                )
            return fd

        with patch.object(snapshot_module.os, "open",
                          side_effect=recover_after_marker_open):
            live = snapshot_module.PrivateSourceSnapshots(source.parent)
        try:
            self.assertEqual(len(observed), 1)
            self.assertEqual(
                observed[0]["removed"], 0,
                "Recovery removed a worker snapshot before its lease lock",
            )
            self.assertTrue(Path(live.name).is_dir())
            staged = Path(live.name) / "synthetic.mp4"
            shutil.copyfile(source, staged)
            self.assertEqual(sha256(staged), sha256(source))
            real_command(
                "ffmpeg", "-nostdin", "-v", "error", "-xerror",
                "-i", str(staged), "-an", "-f", "null", "-",
            )
        finally:
            live.cleanup()


    def test_cache_hit_must_not_return_stale_master_if_source_changes_during_lookup(self):
        """A cached RED master must not be served after its source becomes BLUE.

        The mutation is placed AFTER the service fingerprints source bytes,
        exactly when it enumerates cached master records. This is distinct
        from sequential cache invalidation and in-flight FFmpeg mutation.
        Both source generations are real H.264; any returned master must
        have matching SHA lineage, ffprobe metadata and decoded pixels.
        """
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        original_sha = sha256(source)
        first = service.assemble_project_master(project.id, request)
        self.assertEqual(first["source_asset_hashes"], [original_sha])
        self.assert_real_media(first, "red")
        # Establish that an unchanged source actually exercises the cache.
        self.assertEqual(
            service.assemble_project_master(project.id, request)["id"],
            first["id"],
        )

        original_list = service.list_video_records
        changed_hashes = []

        def mutate_at_cached_master_enumeration(kind):
            if kind == "video_master" and not changed_hashes:
                encode_synthetic(source, "blue")
                changed_hashes.append(sha256(source))
            return original_list(kind)

        with patch.object(service, "list_video_records",
                          side_effect=mutate_at_cached_master_enumeration):
            try:
                refreshed = service.assemble_project_master(project.id, request)
            except service.MasterAssemblyNotReady:
                # A fresh source-integrity check may reject the racing call.
                self.assertEqual(len(changed_hashes), 1)
                self.assertNotEqual(changed_hashes[0], original_sha)
                self.assertEqual(sha256(source), changed_hashes[0])
                return

        self.assertEqual(len(changed_hashes), 1,
                         "The cached-master lookup mutation hook did not run")
        self.assertNotEqual(changed_hashes[0], original_sha)
        self.assertEqual(sha256(source), changed_hashes[0])
        self.assertNotEqual(
            refreshed["id"], first["id"],
            "Cache returned the old RED master after source changed to BLUE",
        )
        self.assertEqual(refreshed["source_asset_hashes"], [changed_hashes[0]])
        self.assert_real_media(refreshed, "blue")


    def test_completed_master_output_file_is_private_during_and_after_ffmpeg(self):
        """Master footage must be owner-only, including during FFmpeg encoding.

        The workspace and video-assets directories may be traversable under a
        standard 022 umask. Real libx264 output must not be created as 0644
        before its authenticated download endpoint serves it. Capture mode
        immediately after the real FFmpeg process finishes and verify the
        persisted, fully decoded H.264 master retains owner-only permissions.
        """
        project, _source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        original_runner = service._run_master_ffmpeg
        observed = []

        def run_real_ffmpeg_and_capture_output_mode(command, **kwargs):
            result = original_runner(command, **kwargs)
            output = Path(command[-1])
            self.assertTrue(output.is_file(), "Actual FFmpeg master was not written")
            observed.append(stat.S_IMODE(output.stat().st_mode))
            return result

        previous_umask = os.umask(0o022)
        try:
            with patch.object(
                service, "_run_master_ffmpeg",
                side_effect=run_real_ffmpeg_and_capture_output_mode,
            ):
                master = service.assemble_project_master(project.id, request)
        finally:
            os.umask(previous_umask)

        self.assert_real_media(master, "red")
        output = storage.video_asset_path(master["asset_id"], "mp4")
        self.assertEqual(
            observed, [0o600],
            "Real FFmpeg created a group/other-readable cinematic master",
        )
        self.assertEqual(
            stat.S_IMODE(output.stat().st_mode), 0o600,
            "Persisted private cinematic master is group/other-readable",
        )


    @unittest.skipUnless(os.name == "posix", "POSIX private cached-master mode")
    def test_cache_hit_must_not_reuse_group_readable_legacy_master(self):
        """A valid SHA and source fingerprint do not make an MP4 private.

        Simulate a legacy 0644 master created before the 0600 output fix.
        Its bytes, FFprobe metadata, source SHA and project revision remain
        valid, so this exercises the real cache-hit authorization/privacy
        decision rather than a broken media record. A returned master must
        be private; fail-closed refusal is also acceptable.
        """
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        first = service.assemble_project_master(project.id, request)
        self.assert_real_media(first, "red")
        output = storage.video_asset_path(first["asset_id"], "mp4")
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        original_hash = sha256(output)
        os.chmod(output, 0o644)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o644)
        self.assertEqual(sha256(output), original_hash)
        self.assertEqual(first["source_asset_hashes"], [sha256(source)])

        try:
            reused = service.assemble_project_master(project.id, request)
        except service.MasterAssemblyNotReady:
            # Explicit rejection is safer than reusing the public inode.
            return
        self.assert_real_media(reused, "red")
        reused_path = storage.video_asset_path(reused["asset_id"], "mp4")
        self.assertEqual(
            stat.S_IMODE(reused_path.stat().st_mode) & 0o077, 0,
            "Cache served a group/other-readable legacy master despite "
            "valid media SHA, source fingerprint and project revision",
        )



    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
        "POSIX no-follow private master cache",
    )
    def test_cache_hit_must_not_follow_symlinked_master_outside_asset_store(self):
        """A valid hash and 0600 target cannot authorize a symlinked master.

        A local file replacement can make a cached master path a symlink to
        bytes outside the managed asset directory. The media, persisted hash,
        source fingerprint, revision and target file mode all remain valid.
        Cache reuse must fail closed or return a regular managed output; a
        path-following cache check would accept an unsafe filesystem entry.
        This is synthetic filesystem-integrity QA, not a remote exploit.
        """
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        first = service.assemble_project_master(project.id, request)
        self.assert_real_media(first, "red")
        output = storage.video_asset_path(first["asset_id"], "mp4")
        self.assertFalse(output.is_symlink())
        original_sha = sha256(output)
        external = output.parent.parent / (
            f".synthetic-cinematic-external-{uuid4().hex}.mp4"
        )
        shutil.copyfile(output, external)
        os.chmod(external, 0o600)
        self.assertEqual(sha256(external), original_sha)
        self.assertEqual(first["source_asset_hashes"], [sha256(source)])
        output.unlink()
        output.symlink_to(external)
        try:
            self.assertTrue(output.is_symlink())
            self.assertEqual(sha256(output), original_sha)
            self.assertEqual(stat.S_IMODE(external.stat().st_mode), 0o600)
            try:
                reused = service.assemble_project_master(project.id, request)
            except service.MasterAssemblyNotReady:
                return
            reused_path = storage.video_asset_path(reused["asset_id"], "mp4")
            self.assertFalse(
                reused_path.is_symlink(),
                "Cache accepted a symlinked master pointing outside "
                "the private asset directory despite valid SHA and mode",
            )
            self.assert_real_media(reused, "red")
        finally:
            if output.is_symlink():
                output.unlink()
            external.unlink(missing_ok=True)



    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "O_NOFOLLOW"),
        "POSIX no-follow cached master path race",
    )
    def test_cache_hit_must_not_follow_symlink_swapped_after_path_validation(self):
        """Do not trust a pathname check made before opening cached footage.

        This deterministic interleaving replaces the already-validated cached
        path with a symlink to an outside-asset-store 0600 copy *after*
        video_asset_path's symlink guard, before the cached file is opened.
        Real H.264, SHA, source identity and revision all remain unchanged.
        A safe implementation must reject or rebuild, never reuse the
        symlinked record. This is a local race proof, not remote exploitation.
        """
        project, source = self.make_ready_project()
        request = AssembleMasterRequest(expected_revision=project.revision)
        first = service.assemble_project_master(project.id, request)
        self.assert_real_media(first, "red")
        output = storage.video_asset_path(first["asset_id"], "mp4")
        original_sha = sha256(output)
        external = output.parent.parent / (
            f".synthetic-cinematic-race-{uuid4().hex}.mp4"
        )
        shutil.copyfile(output, external)
        os.chmod(external, 0o600)
        self.assertEqual(sha256(external), original_sha)
        self.assertEqual(first["source_asset_hashes"], [sha256(source)])
        original_resolver = service.video_asset_path
        swapped = []

        def replace_after_validation(identifier, extension):
            validated = original_resolver(identifier, extension)
            if identifier == first["asset_id"] and extension == "mp4" and not swapped:
                validated.unlink()
                validated.symlink_to(external)
                swapped.append(True)
            return validated

        try:
            with patch.object(
                service, "video_asset_path", side_effect=replace_after_validation,
            ):
                try:
                    reused = service.assemble_project_master(project.id, request)
                except service.MasterAssemblyNotReady:
                    self.assertEqual(swapped, [True])
                    return
            self.assertEqual(swapped, [True], "Cache path race hook never fired")
            self.assertNotEqual(
                reused["id"], first["id"],
                "Cache reused a symlinked master swapped in after the "
                "asset-path validation, despite SHA and 0600 target mode",
            )
            self.assert_real_media(reused, "red")
        finally:
            if output.is_symlink():
                output.unlink()
            external.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
