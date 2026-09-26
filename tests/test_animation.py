import pytest

from app.core.animation_models import AnimationClip, AnimationTrack, Keyframe
from app.qa.animation import qa_animation_clip


def _kf(t, v=(0.0,)):
    return Keyframe(time_seconds=t, value=v)


def test_track_rejects_non_monotonic_keyframes():
    with pytest.raises(ValueError):
        AnimationTrack(target_joint="hand_l", channel="translation", keyframes=[_kf(1.0), _kf(0.5)])


def test_clip_duration_is_max_keyframe_time():
    clip = AnimationClip(
        name="wave",
        tracks=[AnimationTrack(target_joint="hand_l", channel="rotation_quat", keyframes=[_kf(0.0), _kf(2.5)])],
    )
    assert clip.duration_seconds == 2.5


def test_clip_with_no_tracks_has_zero_duration():
    assert AnimationClip(name="empty").duration_seconds == 0.0


def test_qa_flags_unknown_joint_and_empty_track():
    clip = AnimationClip(
        name="broken",
        tracks=[
            AnimationTrack(target_joint="not_a_bone", channel="translation", keyframes=[_kf(0.0)]),
            AnimationTrack(target_joint="hand_l", channel="translation", keyframes=[]),
        ],
    )
    report = qa_animation_clip(clip, known_joints={"hand_l", "hand_r"})
    assert not report.passed
    assert report.unknown_joint_count == 1
    assert report.empty_track_count == 1


def test_qa_passes_for_known_joint_and_morph_targets():
    clip = AnimationClip(
        name="smile",
        tracks=[
            AnimationTrack(target_joint="morph:smile", channel="weight", keyframes=[_kf(0.0), _kf(1.0)]),
            AnimationTrack(target_joint="jaw", channel="rotation_quat", keyframes=[_kf(0.0)]),
        ],
    )
    report = qa_animation_clip(clip, known_joints={"jaw"})
    assert report.passed
    assert not report.blockers
