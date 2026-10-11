"""Scoped studio operations. Generation never runs in an HTTP request thread."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import io
import os
import time
import uuid
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from app.studio import storage
from app.studio.model_library import get_model, list_models
from app.studio.character import build_character
from app.studio.parameters import CharacterState, human_data
from app.studio.wardrobe import catalog
from app.runtime.capabilities import detect_runtime_readiness

router = APIRouter(prefix='/api/studio', tags=['Browser studio'])
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='studio')


@router.get('/capabilities')
def capabilities():
    return {'backend': True, 'runtime': detect_runtime_readiness().model_dump(mode='json'),
            'auth_required': bool(os.getenv('CHARACTER3D_STUDIO_TOKEN')),
            'character': {'controls': len(human_data()['controls']), 'license': 'CC0-1.0', 'rigged': False},
            'body_editing': {'prompt_review': True,
                             'supported_base_regions': ['breasts', 'glutes', 'hips', 'waist'],
                             'authored_target_regions': ['breasts', 'glutes', 'hips'],
                             'protected_regions': ['breasts', 'glutes', 'hips', 'waist'],
                             'maximum_width_percent': 15,
                             'supported_operations': ['breast_size', 'glute_size', 'hip_width', 'waist_reduce_width'],
                             'percentage_semantics': 'authored_target_strength; not measured anatomical change',
                             'imported_model_prompt_edits': 'unavailable until per-model mappings pass validation'},
            'wardrobe': {'count': len(catalog()), 'construction': 'procedural surface shells'},
            'generation': {'text': ['tripo', 'meshy'], 'image_upload': ['hi3d']}}


@router.get('/controls')
def controls():
    return [{k:v for k,v in c.items() if k not in {'positive','negative'}} for c in human_data()['controls']]


@router.get('/wardrobe')
def wardrobe():
    return catalog()


@router.get('/models')
def models():
    return list_models()


@router.get('/models/{identifier}')
def model(identifier: str):
    try:
        return get_model(identifier)
    except KeyError:
        raise HTTPException(404, 'Model not found')


@router.get('/models/{identifier}/capabilities')
def model_capabilities(identifier: str):
    try:
        metadata = get_model(identifier)
    except KeyError:
        raise HTTPException(404, 'Model not found')
    keys = ('id', 'name', 'source_filename', 'sha256', 'bytes', 'mesh_count',
            'primitive_count', 'triangle_count', 'mesh_summaries', 'material_count',
            'image_count', 'uv_set_count', 'uv_sets', 'skin_count',
            'skin_joint_counts', 'joint_attribute_sets', 'node_count',
            'animation_count', 'animation_names', 'morph_target_count',
            'morph_target_names', 'editing', 'coordinate_scale', 'readiness')
    return {key: metadata[key] for key in keys if key in metadata}


class ProjectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    schema_version: int = Field(default=1, ge=1, le=1)
    character: CharacterState


@router.post('/projects')
def save_project(req: ProjectRequest):
    return storage.put('project', req.model_dump())


@router.get('/projects')
def projects():
    return storage.list_records('project')


@router.get('/projects/{identifier}')
def project(identifier: str):
    try:
        return storage.get('project', identifier)
    except KeyError:
        raise HTTPException(404, 'Project not found')


@router.post('/characters/export')
def export_character(state: CharacterState):
    try:
        scene = build_character(state)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    identifier = uuid.uuid4().hex
    scene.export(storage.asset_path(identifier))
    return {'asset_id': identifier, 'url': f'/api/studio/assets/{identifier}.glb',
            'rigged': False, 'attachments_exported': False, 'construction': 'static authored morphs with surface garments'}


@router.get('/assets/{filename}')
def asset(filename: str):
    try:
        identifier, extension = filename.rsplit('.', 1)
        path = storage.asset_path(identifier, extension)
    except ValueError:
        raise HTTPException(404, 'Asset not found')
    if not path.is_file():
        raise HTTPException(404, 'Asset not found')
    return FileResponse(path, media_type='model/gltf-binary' if extension == 'glb' else 'image/png', filename=filename)


@router.post('/images')
async def upload_image(file: UploadFile = File(...)):
    raw = await file.read(12*1024*1024+1)
    await file.close()
    if len(raw) > 12*1024*1024:
        raise HTTPException(413, 'Image exceeds 12 MiB')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {'PNG','JPEG','WEBP'} or image.width*image.height > 20_000_000:
                raise ValueError('Use PNG/JPEG/WebP up to 20 megapixels')
            from PIL import ImageOps
            image = ImageOps.exif_transpose(image).convert('RGB')
            identifier = uuid.uuid4().hex
            image.save(storage.asset_path(identifier, 'png'), format='PNG')
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, 'Invalid or unsupported image') from exc
    return {'image_id': identifier, 'url': f'/api/studio/assets/{identifier}.png'}


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = 'text'
    provider: str = 'tripo'
    prompt: str = Field(default='', max_length=12000)
    image_id: str | None = None


def update_job(identifier, **changes):
    value = storage.get('job', identifier)
    value.pop('id')
    return storage.put('job', {**value, **changes}, identifier)


def execute_generation(identifier, req):
    client = None
    try:
        from app.providers.execution import CanonicalTaskStatus, api_key_from_env
        from app.providers.ingest import ingest_terminal_snapshot
        from app.providers.tripo import TripoClient
        from app.providers.meshy import MeshyClient
        from app.providers.hi3d import Hi3DClient

        update_job(identifier, status='running', stage='Submitting')
        client = {'tripo': TripoClient, 'meshy': MeshyClient, 'hi3d': Hi3DClient}[req.provider](
            api_key_from_env({'tripo':'TRIPO_API_KEY','meshy':'MESHY_API_KEY','hi3d':'HI3D_API_KEY'}[req.provider]))
        if req.kind == 'image':
            task_id, _ = client.create_image_file(storage.asset_path(req.image_id, 'png'))
            query = client.query
        elif req.provider == 'tripo':
            task_id = client.create_text(req.prompt)
            query = client.query
        else:
            task_id = client.create_text_preview(req.prompt)
            query = client.query_text
        update_job(identifier, task_id=task_id, stage='Generating')
        for phase in range(2 if req.provider == 'meshy' else 1):
            for _ in range(300):
                snapshot = query(task_id)
                update_job(identifier, provider_progress=snapshot.progress)
                if snapshot.terminal:
                    break
                time.sleep(2)
            else:
                raise RuntimeError('Polling timed out; remote task may still be running. Do not automatically resubmit.')
            if snapshot.status != CanonicalTaskStatus.SUCCEEDED:
                raise RuntimeError(snapshot.error or 'Provider generation failed')
            if req.provider == 'meshy' and phase == 0:
                task_id = client.create_text_refine(task_id, texture_resolution='4k')
                update_job(identifier, refine_task_id=task_id, stage='Texturing')
        update_job(identifier, stage='Verifying assets')
        admitted = ingest_terminal_snapshot(snapshot, storage.root()/'jobs'/identifier, max_asset_bytes=100_000_000)
        model = next((a for a in admitted.assets if a.format == 'glb' and a.local_path), None)
        if model is None:
            raise RuntimeError('Provider returned no GLB model')
        import shutil
        from app.exports.gltf_validation import validate_gltf_structure
        # GLB loader checks below establish a real readable model; existing deep
        # structural QA remains separately available on the pipeline APIs.
        import trimesh
        if not validate_gltf_structure(model.local_path).passed:
            raise RuntimeError('Provider GLB failed structural validation')
        if not trimesh.load(model.local_path, force='scene').geometry:
            raise RuntimeError('Provider returned an empty model')
        asset_id = uuid.uuid4().hex
        shutil.copyfile(model.local_path, storage.asset_path(asset_id))
        update_job(identifier, status='succeeded', stage='Ready', asset_id=asset_id,
                   asset_url=f'/api/studio/assets/{asset_id}.glb', sha256=model.sha256,
                   evidence='live', fully_morph_compatible=False)
    except Exception as exc:
        # Credentials must never become persisted error text.
        message = str(exc)
        for env in ('TRIPO_API_KEY','MESHY_API_KEY','HI3D_API_KEY'):
            key = os.getenv(env)
            if key and key.strip():
                message = message.replace(key, '[redacted]').replace(key.strip(), '[redacted]')
        update_job(identifier, status='failed', stage='Stopped', error=message[:1000])
    finally:
        close = getattr(getattr(client, 'transport', None), 'close', None)
        if close:
            # Cleanup must not replace a persisted result or provider failure.
            with suppress(Exception):
                close()


@router.post('/generate')
def generate(req: GenerationRequest):
    if req.kind not in {'text', 'image'} or req.provider not in {'tripo','meshy','hi3d'}:
        raise HTTPException(422, 'Unsupported creation mode/provider')
    if req.kind == 'text' and (not req.prompt.strip() or req.provider == 'hi3d'):
        raise HTTPException(422, 'Text requires a prompt and Tripo or Meshy')
    if req.kind == 'text' and req.provider == 'tripo' and len(req.prompt) > 1024:
        raise HTTPException(422, 'Tripo prompt exceeds 1024 characters')
    if req.kind == 'image':
        try:
            valid = req.provider == 'hi3d' and req.image_id and storage.asset_path(req.image_id, 'png').is_file()
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(422, 'Image upload generation currently requires Hi3D and a valid uploaded image')
    from app.core.content_filters import scan_text
    if req.prompt and scan_text(req.prompt).hard_blocked:
        raise HTTPException(422, 'Prompt rejected by content policy')
    configured = next((p.available for p in detect_runtime_readiness().providers if p.name == f'provider:{req.provider}'), False)
    if not configured:
        raise HTTPException(503, f'{req.provider} credentials are not configured on this server')
    try:
        job = storage.enqueue_job({'provider': req.provider, 'created': time.time()})
    except storage.JobCapacityError as exc:
        raise HTTPException(429, str(exc)) from exc
    try:
        pool.submit(execute_generation, job['id'], req)
    except RuntimeError as exc:
        update_job(job['id'], status='failed', stage='Stopped', error='Generation worker is unavailable. Please retry.')
        raise HTTPException(503, 'Generation worker is unavailable. Please retry.') from exc
    return job


@router.get('/jobs')
def jobs():
    return storage.list_records('job')


@router.get('/jobs/{identifier}')
def job(identifier: str):
    try:
        return storage.get('job', identifier)
    except KeyError:
        raise HTTPException(404, 'Job not found')
