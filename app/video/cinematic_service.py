from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable

from app.video.cinematic_compiler import compile_project_prompt
from app.video.cinematic_models import (
    CinematicProject,
    CinematicScene,
    CinematicShot,
    ContinuityState,
    DeliveryResolution,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    RenderPlan,
    merge_continuity,
    MAX_FILM_DURATION_SECONDS,
)
from app.video.cinematic_requests import CompileProjectRequest, ShotRenderRequest
from app.video.models import EngineCapabilities
from app.video.storage import (
    compare_and_swap_video_project,
    get_video_record,
    list_video_records,
    put_video_record,
    video_asset_path,
)


_RESOLUTION_HEIGHT = {
    '480p': 480,
    '720p': 720,
    '1080p': 1080,
    '1440p': 1440,
    '2160p': 2160,
}


class ProjectRevisionConflict(RuntimeError):
    def __init__(self, project_id: str, expected_revision: int, actual_revision: int):
        self.project_id = project_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f'Project {project_id} revision conflict: expected {expected_revision}, actual {actual_revision}'
        )


class FilmDurationExceeded(ValueError):
    """The authored target or actual shot timeline exceeds the current limit."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _project_payload(project: CinematicProject) -> dict:
    return project.model_dump(mode='json', exclude={'id'})


def enforce_film_duration(project: CinematicProject) -> None:
    """Keep legacy projects readable while blocking overlong edits and work."""
    actual = sum((Decimal(str(shot.duration_seconds)) for scene in project.scenes for shot in scene.shots), Decimal(0))
    if project.target_duration_seconds > MAX_FILM_DURATION_SECONDS or actual > Decimal(MAX_FILM_DURATION_SECONDS) + Decimal('0.000001'):
        raise FilmDurationExceeded('Film duration cannot exceed 600 seconds (10 minutes). Shorten the target and shot timeline before rendering.')


def create_project(request: ProjectCreateRequest) -> CinematicProject:
    now = _utcnow()
    project = CinematicProject(
        revision=1,
        title=request.title,
        master_prompt=request.master_prompt,
        target_duration_seconds=request.target_duration_seconds,
        delivery_fps=request.delivery_fps,
        delivery_resolution=request.delivery_resolution,
        aspect_ratio=request.aspect_ratio,
        continuity_bible=request.continuity_bible,
        reference_image_ids=request.reference_image_ids,
        scenes=[],
        created_at=now,
        updated_at=now,
    )
    enforce_film_duration(project)
    record = put_video_record('video_project', _project_payload(project))
    return CinematicProject.model_validate(record)


def get_project(project_id: str) -> CinematicProject:
    return CinematicProject.model_validate(get_video_record('video_project', project_id))


def list_projects() -> list[CinematicProject]:
    return [CinematicProject.model_validate(record) for record in list_video_records('video_project')]



def _effective_shot_render_intent(
    project: CinematicProject, scene: CinematicScene, shot: CinematicShot,
) -> dict:
    """In-memory rendering-intent comparison, never exported in diagnostics.

    A job link is not durable evidence that its clip matches revised creative
    instructions. This includes conservative scene/script and delivery changes.
    It deliberately excludes identifiers, titles and *result* link metadata.
    """
    return {
        'master_prompt': project.master_prompt,
        'delivery_fps': project.delivery_fps,
        'delivery_resolution': project.delivery_resolution,
        'aspect_ratio': project.aspect_ratio,
        'project_references': project.reference_image_ids,
        'scene_references': scene.reference_image_ids,
        'scene_source_text': scene.source_text,
        'scene_synopsis': scene.synopsis,
        'scene_ordinal': scene.ordinal,
        'scene_duration': scene.target_duration_seconds,
        'shot': shot.model_dump(
            mode='python',
            exclude={
                'title', 'latest_job_id', 'latest_asset_url',
                'latest_rendered_project_revision',
            },
        ),
        'continuity': merge_continuity(
            merge_continuity(project.continuity_bible, scene.continuity_patch),
            shot.continuity_patch,
        ).model_dump(mode='python'),
    }


def _shot_render_provenance_digest(
    project: CinematicProject,
    scene: CinematicScene,
    shot: CinematicShot,
    *,
    engine_name: str,
    native_fps: int,
    native_resolution: str,
    source_digests: dict[str, str] | None = None,
) -> str:
    """Bind creative inputs and authentic reference-image bytes to a render.

    The digest is versioned and never contains private text or image data in
    its persisted form. A cache is valid only within one status/queue/assembly
    operation; cross-request file changes must always be rehashed.
    """
    if not isinstance(engine_name, str) or not engine_name:
        raise ValueError('Render engine identity is missing')
    if type(native_fps) is not int or native_fps < 1:
        raise ValueError('Native render FPS is invalid')
    if not isinstance(native_resolution, str) or not native_resolution:
        raise ValueError('Native render resolution is missing')
    image_hashes: list[tuple[str, str]] = []
    cache = source_digests if source_digests is not None else {}
    for identifier in resolve_reference_ids(
        project, scene, shot, require_assets=False,
    ):
        if identifier not in cache:
            image_file = video_asset_path(identifier, 'png')
            with image_file.open('rb') as handle:
                cache[identifier] = hashlib.file_digest(handle, 'sha256').hexdigest()
        image_hashes.append((identifier, cache[identifier]))
    envelope = {
        'format_version': 1,
        'intent': _effective_shot_render_intent(project, scene, shot),
        'source_image_sha256': image_hashes,
        'engine': engine_name,
        'generation_fps': native_fps,
        'generation_resolution': native_resolution,
        'prompt_pack_version': 1,
    }
    return hashlib.sha256(json.dumps(
        envelope, sort_keys=True, ensure_ascii=True, allow_nan=False,
        separators=(',', ':'),
    ).encode('utf-8')).hexdigest()


def _invalidate_stale_shot_links(
    previous: CinematicProject, candidate: CinematicProject,
) -> CinematicProject:
    """Detach old results when a shot's effective input intent changes.

    Completed asset/job records remain untouched for provenance. The changed
    shot becomes missing; only explicit owner-initiated retry can render again.
    This does not prove unchanged bytes behind an opaque reference-image ID.
    """
    original_scenes = {scene.scene_id: scene for scene in previous.scenes}
    scenes: list[CinematicScene] = []
    for scene in candidate.scenes:
        prior_scene = original_scenes.get(scene.scene_id)
        previous_shots = (
            {shot.shot_id: shot for shot in prior_scene.shots}
            if prior_scene is not None else {}
        )
        shots: list[CinematicShot] = []
        for shot in scene.shots:
            earlier = previous_shots.get(shot.shot_id)
            valid_old_link = (
                prior_scene is not None
                and earlier is not None
                and _effective_shot_render_intent(previous, prior_scene, earlier)
                == _effective_shot_render_intent(candidate, scene, shot)
            )
            if not valid_old_link:
                shot = shot.model_copy(update={
                    'latest_job_id': None,
                    'latest_asset_url': None,
                    'latest_rendered_project_revision': None,
                })
            shots.append(shot)
        scenes.append(scene.model_copy(update={'shots': shots}))
    return candidate.model_copy(update={'scenes': scenes})


def update_project(project_id: str, request: ProjectUpdateRequest) -> CinematicProject:
    current = get_project(project_id)
    if current.revision != request.expected_revision:
        raise ProjectRevisionConflict(project_id, request.expected_revision, current.revision)

    patch = request.model_dump(mode='python', exclude={'expected_revision'}, exclude_none=True)
    data = current.model_dump(mode='python', exclude={'id'})
    data.update(patch)
    data['revision'] = current.revision + 1
    data['updated_at'] = _utcnow()
    candidate = CinematicProject.model_validate(data)
    enforce_film_duration(candidate)
    candidate = _invalidate_stale_shot_links(current, candidate)
    payload = _project_payload(candidate)

    updated, actual_revision, record = compare_and_swap_video_project(
        project_id,
        expected_revision=request.expected_revision,
        data=payload,
    )
    if not updated or record is None:
        raise ProjectRevisionConflict(project_id, request.expected_revision, actual_revision)
    return CinematicProject.model_validate(record)


def compile_project(
    project_id: str,
    request: CompileProjectRequest,
) -> tuple[CinematicProject, dict]:
    project = get_project(project_id)
    if project.revision != request.expected_revision:
        raise ProjectRevisionConflict(project_id, request.expected_revision, project.revision)

    enforce_film_duration(project)

    engine_cap = request.engine_max_duration_seconds
    if request.engine_name:
        from app.video.engine import get_engine

        engine_cap = min(engine_cap, get_engine(request.engine_name).capabilities().max_duration_seconds)

    result = compile_project_prompt(
        project,
        preferred_shot_seconds=request.preferred_shot_seconds,
        engine_max_duration_seconds=engine_cap,
    )
    updated = update_project(
        project_id,
        ProjectUpdateRequest(
            expected_revision=request.expected_revision,
            scenes=result.scenes,
        ),
    )
    diagnostics = {
        **result.diagnostics,
        'project_revision': updated.revision,
        'engine_duration_cap_seconds': float(engine_cap),
    }
    return updated, diagnostics


def resolve_effective_continuity(
    project: CinematicProject,
    scene: CinematicScene,
    shot: CinematicShot,
) -> ContinuityState:
    scene_state = merge_continuity(project.continuity_bible, scene.continuity_patch)
    return merge_continuity(scene_state, shot.continuity_patch)


def _ordered_unique(groups: Iterable[Iterable[str]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for identifier in group:
            if identifier not in seen:
                seen.add(identifier)
                ordered.append(identifier)
    return ordered


def resolve_reference_ids(
    project: CinematicProject,
    scene: CinematicScene,
    shot: CinematicShot,
    *,
    require_assets: bool = True,
) -> list[str]:
    identifiers = _ordered_unique(
        (project.reference_image_ids, scene.reference_image_ids, shot.reference_image_ids)
    )
    if require_assets:
        for identifier in identifiers:
            path = video_asset_path(identifier, 'png')
            if not path.is_file():
                raise FileNotFoundError(f'Reference image {identifier} was not found')
    return identifiers


def find_scene(project: CinematicProject, scene_id: str) -> CinematicScene:
    for scene in project.scenes:
        if scene.scene_id == scene_id:
            return scene
    raise KeyError(scene_id)


def find_shot(scene: CinematicScene, shot_id: str) -> CinematicShot:
    for shot in scene.shots:
        if shot.shot_id == shot_id:
            return shot
    raise KeyError(shot_id)


def select_native_fps(delivery_fps: int, supported_fps: list[int]) -> int:
    if not supported_fps:
        raise ValueError('engine declares no supported FPS values')
    supported = sorted(set(int(value) for value in supported_fps))
    at_or_below = [value for value in supported if value <= delivery_fps]
    return max(at_or_below) if at_or_below else min(supported)


def select_native_resolution(
    delivery_resolution: DeliveryResolution,
    supported_resolutions: list[str],
) -> DeliveryResolution:
    if not supported_resolutions:
        raise ValueError('engine declares no supported resolutions')
    invalid = [value for value in supported_resolutions if value not in _RESOLUTION_HEIGHT]
    if invalid:
        raise ValueError(f'engine declares unsupported resolution labels: {invalid!r}')
    target = _RESOLUTION_HEIGHT[delivery_resolution]
    supported = sorted(set(supported_resolutions), key=_RESOLUTION_HEIGHT.__getitem__)
    at_or_below = [value for value in supported if _RESOLUTION_HEIGHT[value] <= target]
    chosen = max(at_or_below, key=_RESOLUTION_HEIGHT.__getitem__) if at_or_below else supported[0]
    return chosen  # type: ignore[return-value]


def build_render_plan_from_objects(
    project: CinematicProject,
    scene: CinematicScene,
    shot: CinematicShot,
    capabilities: EngineCapabilities,
    *,
    require_assets: bool = True,
) -> RenderPlan:
    enforce_film_duration(project)
    if project.id is None:
        raise ValueError('project must have a persisted id before rendering')
    if not capabilities.available:
        raise RuntimeError(f'engine {capabilities.name!r} is not available')
    if shot.engine_profile not in capabilities.profiles:
        raise ValueError(f'engine profile {shot.engine_profile!r} is not supported by {capabilities.name}')
    if not capabilities.min_duration_seconds <= shot.duration_seconds <= capabilities.max_duration_seconds:
        raise ValueError(
            f'shot duration {shot.duration_seconds} is outside engine range '
            f'{capabilities.min_duration_seconds}..{capabilities.max_duration_seconds}'
        )
    if shot.motion_strength is not None and not capabilities.supports_motion_strength:
        raise ValueError(f'motion_strength is not supported by {capabilities.name}')
    if shot.camera_motion is not None and shot.camera_motion not in capabilities.camera_motion_presets:
        raise ValueError(f'camera_motion {shot.camera_motion!r} is not supported by {capabilities.name}')

    references = resolve_reference_ids(project, scene, shot, require_assets=require_assets)
    continuity = resolve_effective_continuity(project, scene, shot)
    generation_fps = select_native_fps(project.delivery_fps, capabilities.supported_fps)
    generation_resolution = select_native_resolution(
        project.delivery_resolution,
        list(capabilities.supported_resolutions),
    )
    return RenderPlan(
        project_id=project.id,
        project_revision=project.revision,
        scene_id=scene.scene_id,
        shot_id=shot.shot_id,
        engine_name=capabilities.name,
        engine_profile=shot.engine_profile,
        prompt=shot.prompt,
        negative_prompt=shot.negative_prompt,
        effective_continuity=continuity,
        reference_image_ids=references,
        source_image_id=references[0] if references else None,
        duration_seconds=shot.duration_seconds,
        seed=shot.seed,
        motion_strength=shot.motion_strength,
        camera_motion=shot.camera_motion,
        generation_fps=generation_fps,
        generation_resolution=generation_resolution,
        delivery_fps=project.delivery_fps,
        delivery_resolution=project.delivery_resolution,
    )


def build_render_plan(
    project_id: str,
    scene_id: str,
    shot_id: str,
    *,
    engine_name: str | None = None,
    require_assets: bool = True,
) -> RenderPlan:
    from app.video.engine import get_engine, select_engine

    project = get_project(project_id)
    scene = find_scene(project, scene_id)
    shot = find_shot(scene, shot_id)
    engine = get_engine(engine_name) if engine_name else select_engine(shot.engine_profile)
    return build_render_plan_from_objects(
        project,
        scene,
        shot,
        engine.capabilities(),
        require_assets=require_assets,
    )


def pack_engine_prompt(plan: RenderPlan, *, max_chars: int = 2000) -> str:
    from app.video.cinematic_rendering import pack_engine_prompt as implementation

    return implementation(plan, max_chars=max_chars)


def render_shot(
    project_id: str,
    scene_id: str,
    shot_id: str,
    request: ShotRenderRequest,
) -> dict:
    from app.video.cinematic_rendering import render_shot as implementation

    return implementation(project_id, scene_id, shot_id, request)


# Project-wide orchestration builds on the proven single-shot render path.
# Keep master assets separate from mutable project documents.
import hashlib
import json
import os
import math
import subprocess
import tempfile
import uuid
from pathlib import Path
from fractions import Fraction

from app.video.cinematic_requests import AssembleMasterRequest, BatchRenderRequest


class MasterAssemblyNotReady(RuntimeError):
    """At least one shot is not a verified successful local job."""


def _linked_shot_job(
    project: CinematicProject, scene: CinematicScene, shot: CinematicShot,
    *, source_digests: dict[str, str] | None = None,
) -> dict | None:
    if not shot.latest_job_id:
        return None
    try:
        job = get_video_record('video_job', shot.latest_job_id)
    except (KeyError, ValueError):
        return None
    if (
        job.get('project_id') != project.id
        or job.get('scene_id') != scene.scene_id
        or job.get('shot_id') != shot.shot_id
    ):
        return None
    expected_digest = job.get('render_intent_sha256')
    if expected_digest is not None:
        # Modern cinematic jobs must match both authored intent and reference
        # bytes, even when someone copies an old matching-ID job link.
        try:
            current_digest = _shot_render_provenance_digest(
                project, scene, shot, engine_name=job['engine'],
                native_fps=job['fps'], native_resolution=job['resolution'],
                source_digests=source_digests,
            )
        except (KeyError, ValueError, TypeError, OSError, OverflowError):
            return None
        if expected_digest != current_digest:
            return None
    # Legacy manually imported jobs without provenance retain historical
    # compatibility. They are NOT verified source-fresh and need migration.
    return job

def _job_has_local_render(job: dict | None) -> bool:
    """Do not trust persisted succeeded state after a file is lost or truncated."""
    if job is None or job.get('status') != 'succeeded':
        return False
    try:
        from app.video.jobs import _valid_mp4
        return _valid_mp4(video_asset_path(job['asset_id'], 'mp4'))
    except (KeyError, TypeError, ValueError, OSError):
        return False


def project_render_status(project_id: str) -> dict:
    """Expose neutral progress metrics without repeating private prompt text."""
    project = get_project(project_id)
    counts = {'missing': 0, 'active': 0, 'failed': 0, 'succeeded': 0}
    shots: list[dict] = []
    missing_assets = 0
    legacy_unverified_shots = 0
    source_digests: dict[str, str] = {}
    for scene in project.scenes:
        for shot in scene.shots:
            job = _linked_shot_job(project, scene, shot, source_digests=source_digests)
            state = job.get('status') if job is not None else None
            if state == 'succeeded':
                category = 'succeeded'
            elif state in {'queued', 'running'}:
                category = 'active'
            elif state == 'failed':
                category = 'failed'
            else:
                category = 'missing'
            counts[category] += 1
            if category == 'succeeded' and job is not None and not job.get('render_intent_sha256'):
                # Historical jobs can be displayed for compatibility but do
                # not carry authoritative SHA-256 input provenance.
                legacy_unverified_shots += 1
            if category == 'succeeded' and not _job_has_local_render(job):
                missing_assets += 1
            shots.append({
                'scene_id': scene.scene_id,
                'shot_id': shot.shot_id,
                'status': category,
                'job_id': job['id'] if job else None,
            })
    assembly_ready = bool(shots) and counts['succeeded'] == len(shots) and not missing_assets
    return {
        'project_id': project.id,
        'project_revision': project.revision,
        'total_shots': len(shots),
        **counts,
        'missing_output_assets': missing_assets,
        'legacy_unverified_shots': legacy_unverified_shots,
        'ready_for_assembly': assembly_ready,
        'ready_with_matching_render_input_digests': assembly_ready and legacy_unverified_shots == 0,
        'shots': shots,
    }


def render_project_missing(project_id: str, request: BatchRenderRequest) -> dict:
    """Submit unscheduled/failed shots in order; never duplicate active jobs."""
    project = get_project(project_id)
    enforce_film_duration(project)
    if project.revision != request.expected_revision:
        raise ProjectRevisionConflict(project_id, request.expected_revision, project.revision)
    submitted: list[dict] = []
    skipped = 0
    source_digests: dict[str, str] = {}
    for scene in project.scenes:
        for shot in scene.shots:
            job = _linked_shot_job(project, scene, shot, source_digests=source_digests)
            if job is not None and (
                job.get('status') in {'queued', 'running'} or _job_has_local_render(job)
            ):
                skipped += 1
                continue
            if len(submitted) >= request.max_shots:
                continue
            # Each link is an atomic revision update. Carry forward its new
            # revision before submitting the next job to prevent stale writes.
            result = render_shot(
                project_id, scene.scene_id, shot.shot_id,
                ShotRenderRequest(expected_revision=project.revision, engine_name=request.engine_name),
            )
            submitted.append(result['job'])
            project = CinematicProject.model_validate(result['project'])
    return {
        'jobs': submitted,
        'skipped': skipped,
        'project': project.model_dump(mode='json'),
    }


def _run_master_ffmpeg(command: list[str], **kwargs):
    """Subprocess seam allows hermetic tests without requiring FFmpeg."""
    return subprocess.run(command, **kwargs)


def _run_master_ffprobe(command: list[str], **kwargs):
    """Probe runner seam; tests may stub it without making a real-media claim."""
    return subprocess.run(command, **kwargs)


def _verify_master_probe(
    output_path, *, project: CinematicProject, shot_count: int, expected_seconds: float,
    ffprobe_path: str,
) -> dict:
    """Fail closed when final media metadata disagrees with the delivery plan.

    ffprobe verifies stream metadata, not artistic quality or frame decode.
    A real decoding/visual playback QA gate remains mandatory for release.
    """
    command = [
        ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries',
        'stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,duration:format=duration',
        '-of', 'json', str(output_path),
    ]
    result = _run_master_ffprobe(
        command, capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode:
        raise RuntimeError('ffprobe rejected the assembled master')
    try:
        info = json.loads(result.stdout)
        stream = next(item for item in info['streams'] if item.get('codec_type') == 'video')
        width = int(stream['width'])
        height = int(stream['height'])
        fps = Fraction(stream['avg_frame_rate'])
        frames = int(stream['nb_frames'])
        duration = float(info.get('format', {}).get('duration') or stream['duration'])
    except (KeyError, TypeError, ValueError, StopIteration, ZeroDivisionError, IndexError) as exc:
        raise RuntimeError('ffprobe did not provide complete valid video metadata') from exc
    expected_width, expected_height = _master_size(project)
    if (width, height) != (expected_width, expected_height):
        raise RuntimeError('Master dimensions do not match the requested delivery dimensions')
    if fps != project.delivery_fps:
        raise RuntimeError('Master FPS does not match the requested delivery FPS')
    if stream.get('codec_name') != 'h264':
        raise RuntimeError('Master codec does not match the FFmpeg H.264 delivery profile')
    if not math.isfinite(duration) or duration <= 0 or frames <= 0:
        raise RuntimeError('Master duration or video frame count is invalid')
    from app.video.cinematic_editing import preflight_editorial_timeline
    planned_frames = preflight_editorial_timeline(project).actual_frames
    if frames != planned_frames or frames > MAX_FILM_DURATION_SECONDS * project.delivery_fps:
        raise RuntimeError('Master frame count does not match the authored timeline')
    if (duration > MAX_FILM_DURATION_SECONDS + 0.001
            or abs(duration - expected_seconds) > 0.5 / project.delivery_fps + 0.002):
        raise RuntimeError('Master duration does not match the authored timeline')
    return {
        'codec': stream['codec_name'],
        'width': width,
        'height': height,
        'fps': str(fps),
        'frame_count': frames,
        'duration_seconds': duration,
        'probe_metadata_verified': True,
        'full_decode_verified': False,
    }


def _master_size(project: CinematicProject) -> tuple[int, int]:
    # The selected label expresses height; width follows the aspect ratio.
    height = _RESOLUTION_HEIGHT[project.delivery_resolution]
    try:
        numerator, denominator = (int(component) for component in project.aspect_ratio.split(':'))
        if numerator <= 0 or denominator <= 0:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValueError('aspect_ratio must be positive integers like 16:9') from exc
    width = max(2, 2 * round((height * numerator / denominator) / 2))
    return width, height


def assemble_project_master(project_id: str, request: AssembleMasterRequest) -> dict:
    """Concatenate ordered local shot videos into a separate, hashed master."""
    project = get_project(project_id)
    enforce_film_duration(project)
    if project.revision != request.expected_revision:
        raise ProjectRevisionConflict(project_id, request.expected_revision, project.revision)

    sources: list[tuple[CinematicScene, CinematicShot, dict]] = []
    source_digests: dict[str, str] = {}
    for scene in project.scenes:
        for shot in scene.shots:
            job = _linked_shot_job(project, scene, shot, source_digests=source_digests)
            if not _job_has_local_render(job):
                continue
            sources.append((scene, shot, job))
    required_shots = sum(len(scene.shots) for scene in project.scenes)
    if not required_shots or len(sources) != required_shots:
        incomplete = required_shots - len(sources)
        raise MasterAssemblyNotReady(
            f'{incomplete} shot(s) are missing successful local render assets'
        )

    from app.video.cinematic_editing import preflight_editorial_timeline
    timeline = preflight_editorial_timeline(project)

    source_ids = [job['asset_id'] for _, _, job in sources]
    source_hashes = []
    for identifier in source_ids:
        with video_asset_path(identifier, 'mp4').open('rb') as source_file:
            source_hashes.append(hashlib.file_digest(source_file, 'sha256').hexdigest())
    # Hash actual media bytes and timeline controls, not just opaque file IDs.
    source_identity = [
        'frame-accurate-master-v2', timeline.timeline_digest_sha256,
        project.id, project.revision, project.delivery_resolution,
        project.delivery_fps, project.aspect_ratio,
        [(shot.shot_id, shot.duration_seconds, job['id'], digest)
         for (_, shot, job), digest in zip(sources, source_hashes)],
    ]
    fingerprint = hashlib.sha256(
        json.dumps(source_identity, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    ).hexdigest()
    for existing in list_video_records('video_master'):
        if existing.get('project_id') != project_id or existing.get('source_digest') != fingerprint:
            continue
        try:
            path = video_asset_path(existing['asset_id'], 'mp4')
        except (KeyError, ValueError, TypeError):
            continue
        probe = existing.get('probe')
        if (isinstance(probe, dict) and probe.get('probe_metadata_verified') is True
                and path.is_file() and path.stat().st_size >= 12):
            with path.open('rb') as cached_file:
                cached_hash = hashlib.file_digest(cached_file, 'sha256').hexdigest()
            if cached_hash == existing.get('sha256'):
                # A source may change after the initial fingerprint and before
                # cached-record enumeration. Never return a master for source
                # bytes that no longer match its recorded provenance.
                try:
                    for source_id, expected_hash in zip(source_ids, source_hashes):
                        with video_asset_path(source_id, 'mp4').open('rb') as source_file:
                            current_hash = hashlib.file_digest(source_file, 'sha256').hexdigest()
                        if current_hash != expected_hash:
                            raise MasterAssemblyNotReady(
                                'Source media changed during cached master lookup; retry'
                            )
                except (OSError, ValueError) as exc:
                    raise MasterAssemblyNotReady(
                        'Source media became unavailable during cached master lookup; retry'
                    ) from exc
                latest_revision = get_project(project_id).revision
                if latest_revision != project.revision:
                    raise ProjectRevisionConflict(project_id, project.revision, latest_revision)
                return existing

    width, height = _master_size(project)
    output_id = uuid.uuid4().hex
    output_path = video_asset_path(output_id, 'mp4')
    filters = []
    for index, clip in enumerate(timeline.clips):
        filters.append(
            f'[{index}:v:0]fps={project.delivery_fps},'
            f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,'
            f'setsar=1,format=yuv420p,'
            f'tpad=stop_mode=clone:stop={clip.duration_frames},'
            f'trim=end_frame={clip.duration_frames},setpts=PTS-STARTPTS[v{index}]'
        )
    filters.append(
        ''.join(f'[v{index}]' for index in range(len(sources)))
        + f'concat=n={len(sources)}:v=1:a=0[v]'
    )
    # A source asset can change (and revert) while FFmpeg is reading it.
    # Stage independent, private input bytes and verify the snapshot digest
    # against the cache fingerprint BEFORE passing any input path to FFmpeg.
    # Never hardlink: hardlinks would share mutable source bytes.
    snapshots = None
    output_created = False
    try:
        try:
            from app.video.cinematic_source_snapshots import PrivateSourceSnapshots
            snapshots = PrivateSourceSnapshots(output_path.parent)
        except OSError as exc:
            raise MasterAssemblyNotReady(
                'Unable to stage private master inputs; check local storage'
            ) from exc
        staged_sources = []
        staged_by_id = {}
        for source_id, expected_source_hash in zip(source_ids, source_hashes):
            # A legitimate timeline may reuse one source asset in several shots.
            # Reuse its verified copy rather than duplicating disk consumption.
            if source_id in staged_by_id:
                snapshot, staged_hash = staged_by_id[source_id]
                if staged_hash != expected_source_hash:
                    raise MasterAssemblyNotReady(
                        'Source media changed while staging master inputs; retry'
                    )
                staged_sources.append(snapshot)
                continue
            snapshot = Path(snapshots.name) / f'{source_id}.mp4'
            snapshot_sha = hashlib.sha256()
            try:
                with video_asset_path(source_id, 'mp4').open('rb') as original, open(
                    snapshot, 'xb', opener=lambda path, flags: os.open(path, flags, 0o600)
                ) as staged:
                    while True:
                        chunk = original.read(1024 * 1024)
                        if not chunk:
                            break
                        staged.write(chunk)
                        snapshot_sha.update(chunk)
            except OSError as exc:
                raise MasterAssemblyNotReady(
                    'Unable to stage verified source media; retry'
                ) from exc
            if snapshot_sha.hexdigest() != expected_source_hash:
                raise MasterAssemblyNotReady(
                    'Source media changed while staging master inputs; retry'
                )
            staged_by_id[source_id] = (snapshot, expected_source_hash)
            staged_sources.append(snapshot)

        command = [request.ffmpeg_path, '-nostdin', '-y', '-hide_banner', '-loglevel', 'error']
        for snapshot in staged_sources:
            command.extend(['-i', str(snapshot)])
        command.extend([
            '-filter_complex', ';'.join(filters),
            '-map', '[v]', '-an', '-c:v', 'libx264',
            '-preset', 'medium', '-crf', '18',
            # Explicit muxer CFR fixes MP4 average FPS and last-frame duration
            # (filtergraph fps alone is insufficient on some FFmpeg builds).
            '-r', str(project.delivery_fps), '-fps_mode', 'cfr',
            '-movflags', '+faststart',
            str(output_path),
        ])
        # FFmpeg normally creates output with the process umask (0644 under
        # umask 022). A bearer-protected private film must never become
        # group/other-readable even transiently during encoding. Precreate
        # the UUID output exclusively as 0600; FFmpeg -y truncates the same
        # inode, preserving its permissions. O_EXCL also rejects collisions.
        try:
            output_fd = os.open(
                output_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0),
                0o600,
            )
        except OSError as exc:
            raise MasterAssemblyNotReady(
                'Unable to create private master output; retry'
            ) from exc
        output_created = True
        os.close(output_fd)
        execution = _run_master_ffmpeg(
            command, capture_output=True, text=True, timeout=43200, check=False,
        )
        if execution.returncode != 0:
            raise RuntimeError(f'FFmpeg master assembly failed with exit code {execution.returncode}')
        # Fail closed if a platform/encoder replaced the precreated inode
        # with a group/other-readable file instead of preserving mode 0600.
        if os.name == 'posix' and output_path.stat().st_mode & 0o077:
            raise MasterAssemblyNotReady('Master output permissions are unsafe')
        # A valid MP4 signature guards against absent or empty output.
        # A separate full media probe is required before production release.
        from app.video.jobs import _valid_mp4
        if not _valid_mp4(output_path):
            raise RuntimeError('FFmpeg did not create a valid MP4 container')
        total_seconds = sum(shot.duration_seconds for _, shot, _ in sources)
        ffprobe_path = 'ffprobe.exe' if request.ffmpeg_path == 'ffmpeg.exe' else 'ffprobe'
        probe = _verify_master_probe(
            output_path, project=project, shot_count=len(sources),
            expected_seconds=total_seconds, ffprobe_path=ffprobe_path,
        )
        # Do not advertise a freshly finished master against an edited project.
        latest_revision = get_project(project_id).revision
        if latest_revision != project.revision:
            raise ProjectRevisionConflict(project_id, project.revision, latest_revision)
        # Source MP4s are mutable after the initial cache fingerprint is read.
        # Never publish a ready master with pre-FFmpeg hashes if a source changed.
        # This detects post-fingerprint mutations, but immutable snapshots are
        # still needed to close mutate-and-revert or mid-encode race windows.
        for source_id, expected_source_hash in zip(source_ids, source_hashes):
            try:
                with video_asset_path(source_id, 'mp4').open('rb') as source_file:
                    current_source_hash = hashlib.file_digest(source_file, 'sha256').hexdigest()
            except (OSError, ValueError) as exc:
                raise MasterAssemblyNotReady(
                    'Source media became unavailable during master assembly; retry'
                ) from exc
            if current_source_hash != expected_source_hash:
                raise MasterAssemblyNotReady(
                    'Source media changed during master assembly; retry'
                )
        with output_path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        record = put_video_record('video_master', {
            'status': 'ready',
            'project_id': project_id,
            'project_revision': project.revision,
            'source_digest': fingerprint,
            'assembly_version': 2,
            'timeline_digest_sha256': timeline.timeline_digest_sha256,
            'timeline_frames': timeline.actual_frames,
            'source_shot_count': len(sources),
            'source_shot_ids': [shot.shot_id for _, shot, _ in sources],
            'timeline_seconds': sum(shot.duration_seconds for _, shot, _ in sources),
            'source_job_ids': [job['id'] for _, _, job in sources],
            'source_asset_hashes': source_hashes,
            'asset_id': output_id,
            'asset_url': f'/api/video/assets/{output_id}.mp4',
            'sha256': digest,
            'size_bytes': output_path.stat().st_size,
            'delivery_fps': project.delivery_fps,
            'delivery_resolution': project.delivery_resolution,
            'actual_video_probe_verified': True,
            'probe': probe,
            'has_audio': False,
            'created_at': _utcnow().isoformat(),
        })
        return record
    except Exception:
        if output_created and output_path.exists():
            output_path.unlink()
        raise
    finally:
        if snapshots is not None:
            snapshots.cleanup()
