from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import urlopen
import uuid

from PIL import Image

from app.image.models import ImageEditRequest, ImageEngineCapabilities
from app.studio.storage import root as studio_root
from app.video.runtime import detect_nvidia_gpu


COMFY_WORKFLOW_REVISION = '9afccb38bb9173575411189a75f4fc6cc8acd06c'
COMFY_WORKFLOW_NAME = 'image_flux3_klein_distilled_image_edit.json'
COMFY_MODEL_FILES = (
    'models/diffusion_models/flux3-image-klein-int8-convrot.safetensors',
    'models/text_encoders/qwen3vl_4b_int8_convrot.safetensors',
    'models/text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors',
    'models/vae/flux2-vae.safetensors',
)
COMFY_INT8_MIN_MB = 7680
_SECRET_ENV_MARKERS = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')


@dataclass(frozen=True)
class ComfyProbe:
    available: bool
    detail: str


def _default_comfy_home() -> Path:
    return Path(os.getenv('CHARACTER3D_COMFY_HOME', './vendor/ComfyUI')).expanduser()


def _default_workflow_path() -> Path:
    return Path(
        os.getenv(
            'CHARACTER3D_COMFY_WORKFLOW',
            './vendor/workflows/image_flux3_klein_distilled_image_edit.json',
        )
    ).expanduser()


def _default_comfy_executable() -> str:
    return os.getenv('CHARACTER3D_COMFY_CLI', 'comfy')


def _server_host() -> str:
    return os.getenv('CHARACTER3D_COMFY_HOST', '127.0.0.1').strip() or '127.0.0.1'


def _server_port() -> int:
    try:
        return max(1, min(65535, int(os.getenv('CHARACTER3D_COMFY_PORT', '8188'))))
    except ValueError:
        return 8188


def _timeout_seconds() -> int:
    try:
        return max(120, min(24 * 3600, int(os.getenv('CHARACTER3D_COMFY_TIMEOUT_SECONDS', '3600'))))
    except ValueError:
        return 3600


def _sanitized_child_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(source or os.environ)
    for name in tuple(env):
        upper = name.upper()
        if any(marker in upper for marker in _SECRET_ENV_MARKERS):
            env.pop(name, None)
    env['HF_HUB_OFFLINE'] = '1'
    env['TRANSFORMERS_OFFLINE'] = '1'
    env['COMFY_WHERE'] = 'local'
    return env


def _resolved_executable(executable: str) -> str | None:
    candidate = Path(executable).expanduser()
    if candidate.is_file():
        return str(candidate)
    return shutil.which(executable)


def probe_comfy_server(host: str, port: int) -> ComfyProbe:
    if host not in {'127.0.0.1', 'localhost', '::1'}:
        return ComfyProbe(False, 'ComfyUI must bind to loopback for this private local adapter')
    try:
        with urlopen(f'http://{host}:{port}/system_stats', timeout=1.5) as response:
            if 200 <= int(getattr(response, 'status', 200)) < 300:
                return ComfyProbe(True, 'ComfyUI loopback server ready')
    except Exception:
        pass
    return ComfyProbe(False, f'ComfyUI is not reachable on {host}:{port}')


def patch_workflow(
    workflow: dict[str, Any],
    *,
    source_name: str,
    prompt: str,
    seed: int,
    output_prefix: str,
) -> dict[str, Any]:
    patched = deepcopy(workflow)
    nodes = patched.get('nodes')
    if not isinstance(nodes, list):
        raise RuntimeError('Pinned ComfyUI workflow has an invalid node list')

    seen = {'LoadImage': 0, 'Flux3LayoutPrompt': 0, 'KSampler': 0, 'SaveImage': 0}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get('type')
        values = node.setdefault('widgets_values', [])
        named = node.setdefault('widgets_values_named', {})

        if node_type == 'LoadImage':
            seen['LoadImage'] += 1
            if values:
                values[0] = source_name
            else:
                values.append(source_name)
            named['image'] = source_name
        elif node_type == 'Flux3LayoutPrompt':
            seen['Flux3LayoutPrompt'] += 1
            if values:
                values[0] = prompt
            else:
                values.append(prompt)
            named['prompt'] = prompt
        elif node_type == 'KSampler':
            seen['KSampler'] += 1
            while len(values) < 2:
                values.append(None)
            values[0] = int(seed)
            values[1] = 'fixed'
            named['seed'] = int(seed)
            named['control_after_generate'] = 'fixed'
        elif node_type == 'CreateBoundingBoxes':
            while len(values) < 4:
                values.append([])
            values[2] = []
            values[3] = []
            named['editor_state'] = []
            named['last_incoming'] = []
        elif node_type == 'SaveImage':
            seen['SaveImage'] += 1
            if values:
                values[0] = output_prefix
            else:
                values.append(output_prefix)
            named['filename_prefix'] = output_prefix

    missing = [name for name, count in seen.items() if count == 0]
    if missing:
        raise RuntimeError(f'Pinned ComfyUI workflow is missing required nodes: {", ".join(missing)}')
    return patched


def _parse_envelope(stdout: str) -> dict[str, Any]:
    envelope = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get('type') == 'envelope':
            envelope = event
    if envelope is None:
        raise RuntimeError('comfy-cli did not return its terminal JSON envelope')
    return envelope


def _cleanup_state_file(envelope: dict[str, Any]) -> None:
    data = envelope.get('data') if isinstance(envelope.get('data'), dict) else {}
    state_file = data.get('state_file')
    if not isinstance(state_file, str) or not state_file:
        return
    try:
        path = Path(state_file).expanduser()
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _copy_output_reference(reference: str, *, comfy_home: Path, destination: Path) -> Path:
    parsed = urlparse(reference)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if parsed.scheme in {'http', 'https'}:
        if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise RuntimeError('ComfyUI returned a non-loopback output URL')
        with urlopen(reference, timeout=30) as response, destination.open('wb') as handle:
            shutil.copyfileobj(response, handle)
        return destination

    candidate = Path(reference).expanduser()
    if not candidate.is_absolute():
        candidate = comfy_home / 'output' / candidate
    resolved = candidate.resolve()
    output_root = (comfy_home / 'output').resolve()
    if not resolved.is_file() or not resolved.is_relative_to(output_root):
        raise RuntimeError('ComfyUI returned an unexpected local output path')
    shutil.copy2(resolved, destination)
    try:
        resolved.unlink()
    except OSError:
        pass
    return destination


class Flux3KleinComfyEngine:
    name = 'flux3_klein_comfy_int8'

    def __init__(
        self,
        *,
        comfy_home: str | Path | None = None,
        workflow_path: str | Path | None = None,
        comfy_executable: str | None = None,
    ):
        self.comfy_home = Path(comfy_home).expanduser() if comfy_home else _default_comfy_home()
        self.workflow_path = Path(workflow_path).expanduser() if workflow_path else _default_workflow_path()
        self.comfy_executable = comfy_executable or _default_comfy_executable()

    def capabilities(self) -> ImageEngineCapabilities:
        problems: list[str] = []
        gpu = detect_nvidia_gpu()
        if gpu is None:
            problems.append('No NVIDIA GPU detected')
        elif gpu['total_mb'] < COMFY_INT8_MIN_MB:
            problems.append(f'FLUX 3 Klein int8 needs an 8 GB-class GPU; detected {gpu["total_mb"]} MiB')

        if _resolved_executable(self.comfy_executable) is None:
            problems.append('comfy-cli is not installed or not on PATH')
        if not self.comfy_home.is_dir():
            problems.append('ComfyUI workspace is missing')
        else:
            missing = [relative for relative in COMFY_MODEL_FILES if not (self.comfy_home / relative).is_file()]
            if missing:
                problems.append(f'Missing {len(missing)} required FLUX 3 Klein int8 model file(s)')
        if not self.workflow_path.is_file():
            problems.append('Pinned FLUX 3 Klein ComfyUI workflow is missing')

        host, port = _server_host(), _server_port()
        probe = probe_comfy_server(host, port)
        if not probe.available:
            problems.append(probe.detail)

        return ImageEngineCapabilities(
            name=self.name,
            available=not problems,
            supports_editing=True,
            precision='int8',
            min_vram_mb=COMFY_INT8_MIN_MB,
            detail='; '.join(problems) if problems else (
                f'FLUX 3 Image Klein int8 via local ComfyUI ready ({gpu["name"] if gpu else "GPU"}; '
                f'workflow {COMFY_WORKFLOW_REVISION[:12]}).'
            ),
        )

    def generate(self, *, request: ImageEditRequest, source_path: Path, output_path: Path, progress) -> Path:
        capabilities = self.capabilities()
        if not capabilities.available:
            raise RuntimeError(capabilities.detail)
        if not source_path.is_file():
            raise FileNotFoundError('Source image does not exist')

        executable = _resolved_executable(self.comfy_executable)
        if executable is None:
            raise RuntimeError('comfy-cli is unavailable')

        input_dir = self.comfy_home / 'input'
        input_dir.mkdir(parents=True, exist_ok=True)
        source_name = f'private-source-{uuid.uuid4().hex}.png'
        comfy_source = input_dir / source_name
        output_prefix = f'private_result_{uuid.uuid4().hex}'
        runtime_dir = studio_root() / 'comfy-runtime'
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_workflow: Path | None = None
        envelope: dict[str, Any] | None = None

        try:
            shutil.copy2(source_path, comfy_source)
            workflow = json.loads(self.workflow_path.read_text(encoding='utf-8'))
            workflow = patch_workflow(
                workflow,
                source_name=source_name,
                prompt=request.prompt,
                seed=request.seed,
                output_prefix=output_prefix,
            )
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                suffix='.json',
                prefix='private-workflow-',
                dir=runtime_dir,
                delete=False,
            ) as handle:
                json.dump(workflow, handle, ensure_ascii=False, separators=(',', ':'))
                runtime_workflow = Path(handle.name)

            progress('generating', 15)
            command = [
                executable,
                '--json',
                '--workspace',
                str(self.comfy_home),
                '--skip-prompt',
                'run',
                '--workflow',
                str(runtime_workflow),
                '--where',
                'local',
                '--wait',
                '--no-notify',
            ]
            completed = subprocess.run(
                command,
                cwd=str(self.comfy_home),
                capture_output=True,
                text=True,
                check=False,
                timeout=_timeout_seconds(),
                shell=False,
                env=_sanitized_child_env(),
            )
            envelope = _parse_envelope(completed.stdout)
            _cleanup_state_file(envelope)
            if completed.returncode != 0 or not envelope.get('ok'):
                error = envelope.get('error') if isinstance(envelope.get('error'), dict) else {}
                message = str(error.get('message') or 'Local ComfyUI generation failed')
                if request.prompt:
                    message = message.replace(request.prompt, '[prompt]')
                raise RuntimeError(message[:1000])

            data = envelope.get('data') if isinstance(envelope.get('data'), dict) else {}
            outputs = data.get('outputs') if isinstance(data.get('outputs'), list) else []
            reference = next((item for item in outputs if isinstance(item, str) and item), None)
            if reference is None:
                raise RuntimeError('ComfyUI completed without returning an image output')
            _copy_output_reference(reference, comfy_home=self.comfy_home, destination=output_path)
            try:
                with Image.open(output_path) as image:
                    if image.format != 'PNG':
                        raise RuntimeError('ComfyUI output is not PNG')
                    image.verify()
            except OSError as exc:
                raise RuntimeError('ComfyUI output could not be validated') from exc
            progress('encoding', 95)
            return output_path
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Local ComfyUI generation exceeded the configured timeout') from exc
        finally:
            if envelope is not None:
                _cleanup_state_file(envelope)
            if runtime_workflow is not None:
                try:
                    runtime_workflow.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                comfy_source.unlink(missing_ok=True)
            except OSError:
                pass
