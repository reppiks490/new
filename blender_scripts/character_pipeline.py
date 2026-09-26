"""Character3D Blender worker entrypoint.

Run with:
    blender --background --disable-autoexec --python character_pipeline.py -- --manifest job.json

This script is intentionally deterministic and conservative. Heavy generation providers are injected
through capability packs; Blender owns scene assembly, modifier/bake preparation, validation and export.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    return parser.parse_args(argv)


def ensure_collections() -> None:
    names = ["C3D_BASE", "C3D_HERO", "C3D_GROOM", "C3D_RIG", "C3D_EXPORT"]
    for name in names:
        if name not in bpy.data.collections:
            coll = bpy.data.collections.new(name)
            bpy.context.scene.collection.children.link(coll)


def configure_scene() -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"  # fast baseline; offline jobs may override to CYCLES.
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.resolution_percentage = 100
    # Metric units reduce cross-DCC scale ambiguity.
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def emit_receipt(manifest: dict, manifest_path: Path) -> None:
    receipt = {
        "schema_version": "character3d-blender-receipt-v1",
        "job_id": manifest.get("job_id"),
        "blender_version": bpy.app.version_string,
        "collections": [c.name for c in bpy.data.collections if c.name.startswith("C3D_")],
        "scene_unit_system": bpy.context.scene.unit_settings.system,
        "status": "scene_initialized",
    }
    receipt_path = manifest_path.with_name("blender_receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ensure_collections()
    configure_scene()
    emit_receipt(manifest, manifest_path)


if __name__ == "__main__":
    main()
