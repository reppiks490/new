from app.core.models import HardwareProfile
from app.core.scene_models import SceneSpec
from app.core.scene_policy import evaluate_scene_policy
from app.pipeline.scene_planner import compile_scene_plan


def test_ordinary_scene_prompt_allowed():
    scene = SceneSpec(name="s", prompt="a quiet forest clearing at dawn")
    assert evaluate_scene_policy(scene).allowed


def test_minor_plus_explicit_scene_prompt_blocked():
    scene = SceneSpec(name="s", prompt="a nude schoolgirl scene")
    decision = evaluate_scene_policy(scene)
    assert not decision.allowed
    assert decision.reasons


def test_nonconsensual_scene_prompt_blocked():
    scene = SceneSpec(name="s", prompt="a forced sex scenario in a warehouse")
    assert not evaluate_scene_policy(scene).allowed


def test_compile_scene_plan_short_circuits_on_blocked_policy():
    scene = SceneSpec(name="s", prompt="a nude schoolgirl scene")
    plan = compile_scene_plan(scene, HardwareProfile())
    assert not plan.policy.allowed
    assert plan.budget is None
    assert plan.scene_manifest_hash is None
    assert not plan.stages


def test_compile_scene_plan_proceeds_when_allowed():
    scene = SceneSpec(name="s", prompt="a quiet forest clearing at dawn")
    plan = compile_scene_plan(scene, HardwareProfile())
    assert plan.policy.allowed
    assert plan.budget is not None
    assert plan.scene_manifest_hash
