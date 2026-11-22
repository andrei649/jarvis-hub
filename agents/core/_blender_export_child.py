"""Fixed Blender-side writer for validated mesh JSON."""

import json
import sys

import bpy


def main():
    source, destination = sys.argv[sys.argv.index("--") + 1:]
    with open(source, encoding="utf-8") as input_file:
        objects = json.load(input_file)
    for existing in list(bpy.data.objects):
        bpy.data.objects.remove(existing, do_unlink=True)
    points = []
    for part in objects:
        mesh = bpy.data.meshes.new(part["name"])
        mesh.from_pydata(part["vertices"], [], part["faces"])
        mesh.update()
        obj = bpy.data.objects.new(part["name"], mesh)
        bpy.context.scene.collection.objects.link(obj)
        points.extend(part["vertices"])
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    low = [min(point[axis] for point in points) for axis in range(3)]
    high = [max(point[axis] for point in points) for axis in range(3)]
    center = [(a + b) / 2 for a, b in zip(low, high)]
    distance = max(max(b - a for a, b in zip(low, high)) * 2, 0.1)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                region = area.spaces.active.region_3d
                region.view_location = center
                region.view_distance = distance
    bpy.ops.wm.save_as_mainfile(filepath=destination, check_existing=False)


if __name__ == "__main__":
    main()
