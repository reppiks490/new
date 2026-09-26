from app.core.models import CharacterSpec, QualityTier, TextureTier
from app.providers.catalog import PROVIDERS
from app.providers.hi3d import high_density_submission_plan, image_task_fields
from app.providers.meshy import refine_request, rigging_compatible, smart_topology_request, text_preview_request
from app.providers.models import Capability, ProviderId
from app.providers.router import RouteContext, compile_provider_routing


def test_hi3d_extends_density_ceiling():
    p = PROVIDERS[ProviderId.HI3D]
    assert p.advertised_max_faces == 5_000_000
    assert Capability.HIGH_DENSITY_5M in p.capabilities
    plan = high_density_submission_plan(5_000_000)
    assert plan.retry_faces == (5_000_000, 2_000_000)
    assert plan.warning


def test_meshy_high_quality_request_builders():
    preview = text_preview_request("adult fictional hero character")
    assert preview["geometry_resolution"] == "4k"
    refine = refine_request("task-1")
    assert refine["texture_resolution"] == "8k"
    assert refine["enable_pbr"] is True


def test_meshy_smart_topology_bounds_and_rig_limit():
    assert smart_topology_request("https://example/model.glb", 15000)["target_polycount"] == 15000
    assert rigging_compatible(300_000)
    assert not rigging_compatible(300_001)


def test_hero_route_prefers_hi3d_for_extreme_geometry():
    spec = CharacterSpec(
        prompt="high fidelity fictional adult character",
        declared_age=28,
        quality_tier=QualityTier.HERO_OFFLINE,
        texture_tier=TextureTier.T8K,
        requested_triangles=5_000_000,
    )
    plan = compile_provider_routing(spec, RouteContext(source_kind="image"))
    extreme = next(r for r in plan.routes if r.stage == "extreme_geometry")
    assert extreme.selected == ProviderId.HI3D
    tex = next(r for r in plan.routes if r.stage == "texture_8k")
    assert tex.selected in {ProviderId.TRIPO, ProviderId.MESHY}


def test_print_route_uses_hi3d_specialization():
    spec = CharacterSpec(prompt="printable figurine")
    plan = compile_provider_routing(spec, RouteContext(source_kind="image", prioritize_printability=True, require_rigging=False))
    pr = next(r for r in plan.routes if r.stage == "print_preparation")
    assert pr.selected == ProviderId.HI3D


def test_hi3d_request_supports_3mf():
    req = image_task_fields(face_count=2_000_000, output_format="3mf")
    assert req["format"] == "6"


def test_provider_profiles_record_review_date():
    for provider_id in (ProviderId.TRIPO, ProviderId.MESHY, ProviderId.HI3D):
        assert PROVIDERS[provider_id].last_reviewed == "2026-09-26"


def test_tripo_rig_creature_types_are_queryable_not_buried_in_notes():
    from app.providers.catalog import providers_supporting_creature_rig

    tripo = PROVIDERS[ProviderId.TRIPO]
    assert tripo.rig_creature_types == [
        "biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic",
    ]
    assert tripo.rig_precheck_endpoint is True
    # Meshy's documented rigging path is humanoid/biped-only; must not be assumed
    # to cover creature types it never documents.
    assert PROVIDERS[ProviderId.MESHY].rig_creature_types == []

    for creature in tripo.rig_creature_types:
        assert ProviderId.TRIPO in providers_supporting_creature_rig(creature)
    assert ProviderId.MESHY not in providers_supporting_creature_rig("quadruped")
    assert ProviderId.MESHY in providers_supporting_creature_rig("biped")


def test_router_excludes_meshy_from_non_biped_rigging():
    spec = CharacterSpec(prompt="a fictional quadruped companion creature", creature_type="quadruped")
    plan = compile_provider_routing(spec, RouteContext(source_kind="image", require_segmentation=False))
    rig = next(r for r in plan.routes if r.stage == "rigging")
    assert rig.selected == ProviderId.TRIPO
    assert ProviderId.MESHY not in rig.alternatives
    assert any("Meshy excluded" in w for w in rig.warnings)


def test_router_keeps_both_providers_for_default_biped_rigging():
    spec = CharacterSpec(prompt="a fictional adult hero character")
    plan = compile_provider_routing(spec, RouteContext(source_kind="image", require_segmentation=False))
    rig = next(r for r in plan.routes if r.stage == "rigging")
    assert rig.selected == ProviderId.TRIPO
    assert ProviderId.MESHY in rig.alternatives
    assert not rig.warnings


def test_gap_fill_matrix_identifies_added_capabilities():
    from app.providers.catalog import gap_fill_capabilities
    gaps = gap_fill_capabilities()
    assert "geometry_4k_pass" in gaps["meshy"]
    assert "uv_unwrap" in gaps["meshy"]
    assert "high_density_5m" in gaps["hi3d"]
    assert "print_split" in gaps["hi3d"]
    assert "multicolor_3d" in gaps["hi3d"]
