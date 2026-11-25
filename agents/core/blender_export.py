"""Turn a bounded, explicitly supported OBJ mesh into a native Blender project."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import tempfile
from pathlib import Path

from agents.core import blender_preview

MAX_BYTES = 256 * 1024
MAX_VERTICES = 8192
MAX_FACES = 8192
MAX_OBJECTS = 64
MAX_FACE_VERTICES = 64
MAX_BLEND_BYTES = 64 * 1024 * 1024


class BlenderExportError(ValueError):
    """OBJ input cannot be represented by this deliberately small exporter."""


class BlenderBuildError(RuntimeError):
    """Native Blender failed after valid input was accepted."""


_FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_INDEX = re.compile(r"[+-]?[0-9]+\Z")


def parse_obj(data: bytes) -> list[dict]:
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise BlenderExportError("Supply OBJ text within 256 KiB")
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BlenderExportError("Supply UTF-8 OBJ text") from exc
    vertices: list[tuple[float, float, float]] = []
    sections: list[dict] = []
    current = {"name": "Mesh", "faces": []}
    names: set[str] = set()
    face_count = 0
    for raw in source.splitlines():
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        directive, content = parts[0], parts[1].strip() if len(parts) == 2 else ""
        if directive == "v":
            fields = content.split()
            if len(fields) != 3:
                raise BlenderExportError("Each vertex needs exactly three XYZ coordinates")
            if any(len(field) > 64 or _FLOAT.fullmatch(field) is None for field in fields):
                raise BlenderExportError("Vertex coordinates must be ASCII decimal numbers")
            point = tuple(float(field) for field in fields)
            if any(not math.isfinite(value) or abs(value) > 10000 for value in point):
                raise BlenderExportError("Vertex coordinates must be finite and within 10000 units")
            vertices.append(point)
            if len(vertices) > MAX_VERTICES:
                raise BlenderExportError("OBJ exceeds 8192 vertices")
        elif directive in ("o", "g"):
            if not content or len(content.encode("utf-8")) > 63 or any(ord(c) < 32 for c in content):
                raise BlenderExportError("Each object or group needs a name within 63 UTF-8 bytes")
            if content in names or (current["name"] == "Mesh" and current["faces"] and content == "Mesh"):
                raise BlenderExportError("Object and group names must be unique")
            if current["faces"]:
                sections.append(current)
                names.add(current["name"])
            elif sections or names:
                raise BlenderExportError("Each named object or group needs at least one face")
            names.add(content)
            current = {"name": content, "faces": []}
            if len(names) > MAX_OBJECTS:
                raise BlenderExportError("OBJ exceeds 64 named objects or groups")
        elif directive == "f":
            fields = content.split()
            if not 3 <= len(fields) <= MAX_FACE_VERTICES:
                raise BlenderExportError("Each face needs 3 to 64 vertex indices")
            face = []
            for field in fields:
                if "/" in field:
                    raise BlenderExportError("Face normals, textures and slash indices are unsupported; use plain vertex indices")
                if len(field) > 16 or _INDEX.fullmatch(field) is None:
                    raise BlenderExportError("Faces need ASCII integer vertex indices")
                index = int(field)
                if index == 0 or abs(index) > len(vertices):
                    raise BlenderExportError("Face index references an undefined vertex")
                face.append(index - 1 if index > 0 else len(vertices) + index)
            if len(set(face)) != len(face):
                raise BlenderExportError("Faces cannot repeat a vertex index")
            current["faces"].append(face)
            face_count += 1
            if face_count > MAX_FACES:
                raise BlenderExportError("OBJ exceeds 8192 faces")
        else:
            raise BlenderExportError(
                "Unsupported OBJ directive; export geometry with only v, o, g and plain f lines"
            )
    if not vertices or not face_count:
        raise BlenderExportError("OBJ needs vertices and at least one face")
    if not current["faces"]:
        raise BlenderExportError("Each named object or group needs at least one face")
    sections.append(current)
    if len(sections) > MAX_OBJECTS:
        raise BlenderExportError("OBJ exceeds 64 mesh objects")
    if {index for section in sections for face in section["faces"] for index in face} != set(range(len(vertices))):
        raise BlenderExportError("OBJ contains vertices unused by faces")
    result = []
    for section in sections:
        used = list(dict.fromkeys(index for face in section["faces"] for index in face))
        local = {index: position for position, index in enumerate(used)}
        result.append({"name": section["name"], "vertices": [vertices[index] for index in used],
                       "faces": [[local[index] for index in face] for face in section["faces"]]})
    return result


def export_obj(data: bytes) -> bytes:
    """Build editable mesh datablocks; no OBJ file or model code enters Blender."""
    objects = parse_obj(data)
    binary = blender_preview._blender_binary()
    if binary is None:
        raise blender_preview.BlenderUnavailable("trusted Blender executable unavailable")
    script = Path(__file__).with_name("_blender_export_child.py")
    if not script.is_file():
        raise blender_preview.BlenderUnavailable("Blender export script unavailable")
    with tempfile.TemporaryDirectory(prefix="nerva-blend-export-") as tmp:
        scratch = Path(tmp)
        source = scratch / "mesh.json"
        destination = scratch / "model.blend"
        command = [str(binary), "--background", "--factory-startup", "--disable-autoexec",
                   "--offline-mode", "--python-exit-code", "1", "--python", str(script),
                   "--", str(source), str(destination)]
        try:
            source.write_text(json.dumps(objects, ensure_ascii=False), encoding="utf-8")
            if os.name == "nt":
                asyncio.run(blender_preview._run_windows_job(
                    command, scratch, blender_preview._child_env(scratch, binary)))
            else:
                blender_preview._run_posix(
                    command, scratch, blender_preview._child_env(scratch, binary))
            if (not destination.is_file() or not 12 <= destination.stat().st_size <= MAX_BLEND_BYTES):
                raise BlenderBuildError("Blender could not save the model")
            with destination.open("rb") as saved:
                header = saved.read(7)
                if not (header == b"BLENDER" or header.startswith(b"\x28\xb5\x2f\xfd")):
                    raise BlenderBuildError("Blender did not produce a native project")
                saved.seek(0)
                return saved.read(MAX_BLEND_BYTES + 1)
        except (OSError, RuntimeError) as exc:
            if isinstance(exc, (blender_preview.BlenderUnavailable, BlenderBuildError)):
                raise
            raise BlenderBuildError("Blender could not save the model") from exc
