"""QA47: actual FFmpeg audio removal and privacy-safe optional detection."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.cinematic_audio_lineage_qa47 import (
    MediaProbeError, audit_audio_presence, main,
)


def run_ffmpeg(*args: str) -> None:
    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                    *args], check=True, capture_output=True, timeout=60)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class RealSyntheticAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.source = root / 'private-owner-canary-source.mp4'
        cls.muted = root / 'private-owner-canary-muted.mp4'
        cls.copied = root / 'private-owner-canary-copied.mp4'
        cls.silent = root / 'private-owner-canary-silent.mp4'
        run_ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=24',
                   '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                   '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                   '-c:a', 'aac', '-shortest', str(cls.source))
        # This mirrors the production assembler's explicit -an audio discard.
        run_ffmpeg('-i', str(cls.source), '-map', '0:v:0', '-an',
                   '-c:v', 'copy', str(cls.muted))
        run_ffmpeg('-i', str(cls.source), '-c', 'copy', str(cls.copied))
        run_ffmpeg('-i', str(cls.source), '-map', '0:v:0', '-an',
                   '-c:v', 'copy', str(cls.silent))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_synthetic_source_audio_is_dropped_by_an(self):
        result = audit_audio_presence([self.source], self.muted)
        self.assertEqual(result['state'], 'source_audio_absent_from_master')
        self.assertEqual(result['sources_with_audio'], 1)
        self.assertFalse(result['master_has_audio'])
        for path in (self.source, self.muted):
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'],
                           check=True, capture_output=True, timeout=60)
        self.assertNotIn('private-owner-canary', json.dumps(result))

    def test_audio_presence_is_not_provenance_or_sync(self):
        result = audit_audio_presence([self.source], self.copied)
        self.assertEqual(result['state'], 'audio_present_provenance_unverified')
        self.assertFalse(result['audio_content_or_sync_verified'])

    def test_video_only_is_not_mislabeled_as_audio_preserved(self):
        result = audit_audio_presence([self.silent], self.muted)
        self.assertEqual(result['state'], 'video_only_sources_and_master')

    def test_mixed_sources_detect_loss(self):
        result = audit_audio_presence([self.silent, self.source], self.muted)
        self.assertEqual(result['source_count'], 2)
        self.assertEqual(result['sources_with_audio'], 1)

    def test_unexpected_master_audio(self):
        result = audit_audio_presence([self.silent], self.copied)
        self.assertEqual(result['state'], 'master_audio_without_source_audio')

    def test_corrupt_media_never_exposes_path(self):
        bad = Path(self.temp.name) / 'owner-secret-private.mp4'
        bad.write_bytes(b'not an MP4')
        with self.assertRaises(MediaProbeError) as ctx:
            audit_audio_presence([bad], self.muted)
        self.assertNotIn('owner-secret', str(ctx.exception))


class HermeticAudioTests(unittest.TestCase):
    def test_reject_empty_or_excessive_sources(self):
        with self.assertRaises(ValueError):
            audit_audio_presence([], Path('out'))
        with self.assertRaises(ValueError):
            audit_audio_presence([Path('in')] * 1001, Path('out'))

    def test_reject_untrusted_ffprobe_binary(self):
        with self.assertRaises(ValueError):
            audit_audio_presence([Path('in')], Path('out'), ffprobe='/tmp/evil')

    def test_timeout_is_sanitized(self):
        with mock.patch('tools.cinematic_audio_lineage_qa47.subprocess.run',
                        side_effect=subprocess.TimeoutExpired(['ffprobe', 'secret'], 1)):
            with self.assertRaises(MediaProbeError) as ctx:
                audit_audio_presence([Path('/private/secret.mp4')], Path('out'))
        self.assertNotIn('secret', str(ctx.exception))

    def test_invalid_probe_json_is_sanitized(self):
        with mock.patch('tools.cinematic_audio_lineage_qa47.subprocess.run',
                        return_value=subprocess.CompletedProcess([], 0, stdout='oops', stderr='private')):
            with self.assertRaises(MediaProbeError) as ctx:
                audit_audio_presence([Path('in')], Path('out'))
        self.assertNotIn('private', str(ctx.exception))

    def test_cli_failure_is_neutral(self):
        from io import StringIO
        with mock.patch('tools.cinematic_audio_lineage_qa47.audit_audio_presence',
                        side_effect=MediaProbeError('hidden')):
            with mock.patch('sys.stdout', new_callable=StringIO) as output:
                code = main(['--source', 'private.mp4', '--master', 'master.mp4'])
        self.assertEqual(code, 2)
        self.assertNotIn('private', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['state'], 'inspection_failed')


if __name__ == '__main__':
    unittest.main()
