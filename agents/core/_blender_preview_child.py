"""Fixed Blender-side inventory; never link or load any named datablock."""

import json
import sys

import bpy

CATEGORIES = ("scenes", "objects", "meshes", "materials", "collections", "cameras", "lights", "actions")


def main():
    source, destination = sys.argv[sys.argv.index("--") + 1:]
    with bpy.data.libraries.load(source, link=False) as (data_from, data_to):
        inventory = {
            category: {"count": len(names), "names": names[:80]}
            for category in CATEGORIES
            for names in (getattr(data_from, category),)
        }
        # data_to remains untouched: no datablocks are imported into this session.
    with open(destination, "w", encoding="utf-8") as output:
        json.dump(inventory, output, ensure_ascii=False)


if __name__ == "__main__":
    main()
