#!/usr/bin/env python3
"""Package the browser studio and selected local models for owner-private hosting.

Original GLB bytes are split, not converted or compressed. No credentials or
workspace database are included. Deployment and audience remain separate steps.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.studio import storage
from app.studio.model_library import get_model

CHUNK_BYTES = 8 * 1024 * 1024
WEB = Path(__file__).resolve().parents[1] / 'app/studio/web'


def package_license_source(destination):
    archive = destination / 'studio/data/quality-assets/source-assets.zip'
    if not archive.exists() or archive.stat().st_size <= 25 * 1024 * 1024:
        return
    chunks, digest, size = [], hashlib.sha256(), archive.stat().st_size
    with archive.open('rb') as source:
        while block := source.read(CHUNK_BYTES):
            name = f'source-{len(chunks):03d}.bin'
            (archive.parent / name).write_bytes(block)
            digest.update(block)
            chunks.append(name)
    payload = json.dumps({'chunks': chunks, 'sha256': digest.hexdigest(), 'bytes': size})
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Original character asset sources</title><style>body{font:18px system-ui;max-width:42em;margin:3em auto;padding:1em;background:#141c26;color:#f0f3f8}button,a{font:inherit;color:inherit}button{background:#34465c;padding:.8em;cursor:pointer}</style>
<h1>Original character asset sources</h1><p>The complete, unchanged source archive for the bundled MakeHuman finish assets is available here. See <a href="CREDITS.md">credits and license</a>.</p>
<button id="download">Download source archive (32.1 MiB)</button><p id="status" role="status"></p>
<script type="module">const source=PAYLOAD;document.querySelector('#download').onclick=async()=>{const b=document.querySelector('#download'),s=document.querySelector('#status');b.disabled=true;try{const data=new Uint8Array(source.bytes);let offset=0;for(const path of source.chunks){s.textContent='Downloading source archive…';const r=await fetch(path);if(!r.ok)throw Error('Download failed');const part=new Uint8Array(await r.arrayBuffer());if(offset+part.length>data.length)throw Error('Invalid source size');data.set(part,offset);offset+=part.length;}const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');if(offset!==data.length||hash!==source.sha256)throw Error('Source integrity check failed');const url=URL.createObjectURL(new Blob([data],{type:'application/zip'})),a=document.createElement('a');a.href=url;a.download='source-assets.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);s.textContent='Verified source archive downloaded.';}catch(e){s.textContent=e.message;}finally{b.disabled=false;}};</script></html>'''.replace('PAYLOAD', payload)
    archive.with_name('source-download.html').write_text(page)
    app = destination / 'studio/app.js'
    app.write_text(app.read_text().replace('quality-assets/source-assets.zip', 'quality-assets/source-download.html'))
    archive.unlink()


def package(destination, identifiers):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Use a new output directory; existing files are never replaced')
    models = [get_model(identifier) for identifier in identifiers]
    if not models or len({m['id'] for m in models}) != len(models):
        raise ValueError('Select at least one model, without duplicate IDs')
    destination.mkdir(parents=True)
    shutil.copytree(WEB, destination / 'studio')
    shutil.copy2(WEB / 'index.html', destination / 'index.html')
    package_license_source(destination)
    manifest = []
    for model in models:
        asset = storage.asset_path(model['id'])
        folder = destination / 'studio/library' / model['id']
        folder.mkdir(parents=True)
        digest, total, chunks = hashlib.sha256(), 0, []
        with asset.open('rb') as source:
            while block := source.read(CHUNK_BYTES):
                name = f'{len(chunks):03d}.bin'
                (folder / name).write_bytes(block)
                chunks.append({'url': f'/studio/library/{model["id"]}/{name}', 'bytes': len(block)})
                digest.update(block)
                total += len(block)
        if total != model['bytes'] or digest.hexdigest() != model['sha256']:
            raise ValueError(f'Source integrity check failed for {model["id"]}; do not publish this output')
        manifest.append({**model, 'chunks': chunks})
    (destination / 'studio/library/index.json').write_text(json.dumps(manifest, indent=2))
    # Exclude editor backup files and accidental large assets before hosting.
    too_large = [str(p.relative_to(destination)) for p in destination.rglob('*')
                 if p.is_file() and p.stat().st_size > 25 * 1024 * 1024]
    if too_large:
        raise ValueError('Hosting file size limit exceeded: ' + ', '.join(too_large))
    return {'models': len(manifest), 'original_bytes': sum(m['bytes'] for m in manifest),
            'chunks': sum(len(m['chunks']) for m in manifest), 'directory': str(destination)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('model_ids', nargs='+')
    args = parser.parse_args()
    print(json.dumps(package(args.destination, args.model_ids)))
