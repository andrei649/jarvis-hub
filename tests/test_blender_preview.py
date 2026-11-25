"""Bounded native Blender library previews."""

import gzip
import struct
import subprocess

import pytest

from agents.core import blender_preview as preview


def test_refuses_unsupported_or_oversized_payload():
    for data in (b"", b"not a blend", b"BLENDER", b"x" * (preview.MAX_BYTES + 1)):
        with pytest.raises(preview.BlenderPreviewError):
            preview.preview_blend(data)


def test_missing_runtime_raises_unavailable(monkeypatch):
    monkeypatch.setattr(preview, "_blender_binary", lambda: None)
    with pytest.raises(preview.BlenderUnavailable):
        preview.preview_blend(b"BLENDER17-01v0503" + b"x" * 64)


def test_formats_exact_counts_and_bounded_names():
    entries = {name: {"count": 100, "names": ["a" * 200] * 80}
               for name in preview.CATEGORIES}
    result = preview._format_inventory(entries, "5.3")
    assert result["kind"] == "blend"
    assert result["total_segments"] == 9
    assert "Scenes: 100" in result["segments"][0]["text"]
    assert "Blender file version: 5.3" in result["segments"][0]["text"]
    assert result["segments"][1]["truncated"] is True
    assert len(result["segments"][1]["text"]) <= 10000


def test_thumbnail_reencodes_a_bounded_test_block():
    rgba = b"\xff\x00\x00\xff"
    block = b"TEST" + struct.pack("<iQqq", 0, 0, 8 + len(rgba), 0)
    data = b"BLENDER17-01v0503" + block + struct.pack("<II", 1, 1) + rgba
    assert preview._thumbnail_png(data) is not None
    assert preview._thumbnail_png(gzip.compress(data)) == preview._thumbnail_png(data)
    legacy = (b"BLENDER-v293" + b"TEST" + struct.pack("<iQii", 8 + len(rgba), 0, 0, 0)
              + struct.pack("<II", 1, 1) + rgba)
    assert preview._thumbnail_png(legacy) == preview._thumbnail_png(data)


def test_real_blend_inventory_when_blender_available(tmp_path):
    binary = preview._blender_binary()
    if binary is None:
        pytest.skip("Blender is not installed")
    fixture = tmp_path / "test.blend"
    subprocess.run(
        [str(binary), "--background", "--factory-startup", "--disable-autoexec", "--offline-mode",
         "--python-exit-code", "1", "--python-expr",
         "import bpy, sys; bpy.context.scene.name = 'Preview fixture'; "
         "bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])", "--", str(fixture)],
        cwd=tmp_path, env=preview._child_env(tmp_path, binary), check=True, timeout=25,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    result = preview.preview_blend(fixture.read_bytes())
    sections = {part["label"]: part["text"] for part in result["segments"]}
    assert "Scenes: 1" in sections["Overview"]
    assert sections["Scenes"] == "Preview fixture"
