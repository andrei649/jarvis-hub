"""Bounded OBJ geometry becomes editable native Blender mesh datablocks."""

import json
import subprocess

import pytest

from agents.core import blender_export as export
from agents.core import blender_preview as preview


OBJ = b"""# global vertices\nv 0 0 0\nv 2 0 0\nv 0 3 0\nv 0 0 4\no Roof\nf 1 2 3 # same winding\ng Side\nf -4 -3 -1\n"""


def test_global_and_negative_indices_preserve_xyz_and_winding():
    assert export.parse_obj(OBJ) == [
        {"name": "Roof", "vertices": [(0, 0, 0), (2, 0, 0), (0, 3, 0)], "faces": [[0, 1, 2]]},
        {"name": "Side", "vertices": [(0, 0, 0), (2, 0, 0), (0, 0, 4)], "faces": [[0, 1, 2]]},
    ]


@pytest.mark.parametrize("body,reason", [
    (b"", "OBJ"), (b"v 0 0 0", "face"), (b"v nan 0 0\nf 1 1 1", "ASCII"),
    (b"v 10001 0 0\nf 1 1 1", "10000"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 1 2", "repeat"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 4", "undefined"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1 2/2 3/3", "slash"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nmtllib private.mtl\nf 1 2 3", "Unsupported"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\no Empty", "needs at least"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\no Mesh\nf 1 2 3", "unique"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\nusemtl Gold", "Unsupported"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nv 4 4 4\nf 1 2 3", "unused"),
    (b"v 0_0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3", "ASCII"),
    ("v ٠ 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3".encode(), "ASCII"),
    (b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf " + b"9" * 5000 + b" 2 3", "ASCII"),
])
def test_rejects_invalid_or_lossy_obj(body, reason):
    with pytest.raises(export.BlenderExportError, match=reason):
        export.parse_obj(body)


def test_limits_apply_before_native_process():
    triangle = b"v 0 0 0\nv 1 0 0\nv 0 1 0\n"
    for body, reason in (
        (b"v 0 0 0\n" * 8193 + b"f 1 2 3\n", "8192 vertices"),
        (triangle + b"f 1 2 3\n" * 8193, "8192 faces"),
        (triangle + b"".join(f"o Part {index}\nf 1 2 3\n".encode() for index in range(65)), "64 named"),
        (b"v 0 0 0\n" * 65 + b"f " + b" ".join(str(i).encode() for i in range(1, 66)), "3 to 64"),
        (b" " * (export.MAX_BYTES + 1), "256 KiB"),
    ):
        with pytest.raises(export.BlenderExportError, match=reason):
            export.parse_obj(body)


def test_real_native_roundtrip(tmp_path):
    binary = preview._blender_binary()
    if binary is None:
        pytest.skip("Blender is not installed")
    saved = tmp_path / "roundtrip.blend"
    saved.write_bytes(export.export_obj(OBJ))
    checked = tmp_path / "checked.json"
    script = tmp_path / "inspect.py"
    script.write_text("""import bpy, json, sys
bpy.ops.wm.open_mainfile(filepath=sys.argv[-2], load_ui=True)
items = []
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        items.append({'name': obj.name, 'vertices': [list(v.co) for v in obj.data.vertices],
                      'faces': [list(p.vertices) for p in obj.data.polygons],
                      'location': list(obj.location), 'rotation': list(obj.rotation_euler),
                      'scale': list(obj.scale)})
with open(sys.argv[-1], 'w') as out:
    views = [{'location': list(area.spaces.active.region_3d.view_location),
              'distance': area.spaces.active.region_3d.view_distance}
             for screen in bpy.data.screens for area in screen.areas if area.type == 'VIEW_3D']
    json.dump({'items': sorted(items, key=lambda x: x['name']), 'views': views,
               'active': bpy.context.view_layer.objects.active.name}, out)
""", encoding="utf-8")
    subprocess.run([str(binary), "--background", "--factory-startup", "--disable-autoexec",
                    "--offline-mode", "--python-exit-code", "1", "--python", str(script),
                    "--", str(saved), str(checked)], cwd=tmp_path,
                   env=preview._child_env(tmp_path, binary), timeout=25, check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checked_data = json.loads(checked.read_text(encoding="utf-8"))
    items = checked_data["items"]
    assert [item["name"] for item in items] == ["Roof", "Side"]
    assert items[0]["vertices"] == [[0, 0, 0], [2, 0, 0], [0, 3, 0]]
    assert items[1]["vertices"] == [[0, 0, 0], [2, 0, 0], [0, 0, 4]]
    assert [item["faces"] for item in items] == [[[0, 1, 2]], [[0, 1, 2]]]
    assert all(item["location"] == [0, 0, 0] and item["rotation"] == [0, 0, 0]
               and item["scale"] == [1, 1, 1] for item in items)
    assert checked_data["active"] == "Side"
    assert checked_data["views"] and all(view["location"] == [1, 1.5, 2]
                                         and view["distance"] == 8 for view in checked_data["views"])
