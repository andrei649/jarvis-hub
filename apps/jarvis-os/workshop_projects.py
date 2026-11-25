"""Versioned workshop scenes stored as ordinary, scoped vault notes."""

from __future__ import annotations

import json
import math
import re

FENCE = re.compile(r"(?m)^```nerva-workshop\n([^`]{1,16000})\n```[ \t]*$")
COLOR = re.compile(r"#[0-9A-Fa-f]{6}\Z")
ROBOT = {"housingColor", "ringColor", "shellColor", "metalness", "roughness", "explode"}
HOUSE = {"mode", "centeredDoorNoStairs", "garageCars", "livingRoomExtraMeters",
         "kitchenExtraMeters", "poolBackPalmsAndFlowers", "poolLoungeChairs", "showRoof",
         "roofVisibilityOverride", "showRoomLabels", "explodedLayers"}
HOUSE_BOOLEANS = HOUSE - {"mode", "livingRoomExtraMeters", "kitchenExtraMeters", "roofVisibilityOverride"}


class InvalidProject(ValueError):
    """A scene cannot safely be saved or loaded."""


class SavedProjectUnavailable(InvalidProject):
    """The note exists, but the guarded index could not reopen it."""

    def __init__(self, path: str):
        super().__init__("saved project could not be reopened")
        self.path = path


def _number(value: object, low: float, high: float) -> bool:
    return type(value) in (int, float) and low <= value <= high and math.isfinite(value)


def validate(project: object) -> dict:
    if type(project) is not dict or set(project) != {"version", "view", "camera", "state"}:
        raise InvalidProject("invalid project schema")
    if type(project["version"]) is not int or project["version"] != 1 or project["view"] not in ("robot", "house"):
        raise InvalidProject("unsupported project version or view")
    camera, state = project["camera"], project["state"]
    if type(camera) is not dict or set(camera) != {"position", "target"} or type(state) is not dict:
        raise InvalidProject("invalid camera or state")
    for point in camera.values():
        if type(point) is not list or len(point) != 3 or not all(_number(axis, -500, 500) for axis in point):
            raise InvalidProject("invalid camera coordinates")
    if camera["position"] == camera["target"]:
        raise InvalidProject("camera position and target must differ")
    if project["view"] == "robot":
        if set(state) != ROBOT or any(type(state[key]) is not str or not COLOR.fullmatch(state[key])
                                      for key in ("housingColor", "ringColor", "shellColor")):
            raise InvalidProject("invalid robot state")
        if any(not _number(state[key], 0, 1) for key in ("metalness", "roughness", "explode")):
            raise InvalidProject("invalid robot material or explosion")
    else:
        if (set(state) != HOUSE or state["mode"] not in ("3d", "miniature")
                or type(state["mode"]) is not str
                or any(type(state[key]) is not bool for key in HOUSE_BOOLEANS)
                or (state["roofVisibilityOverride"] is not None
                    and type(state["roofVisibilityOverride"]) is not bool)
                or not _number(state["livingRoomExtraMeters"], 0, 5)
                or not _number(state["kitchenExtraMeters"], 0, 4)):
            raise InvalidProject("invalid house state")
    return project


def summary(project: dict) -> str:
    state = project["state"]
    if project["view"] == "robot":
        return (f"Robot scene: housing {state['housingColor']}, ring {state['ringColor']}, "
                f"shell {state['shellColor']}; metalness {state['metalness']}, "
                f"roughness {state['roughness']}, exploded {state['explode']}.")
    roof = state["roofVisibilityOverride"]
    roof = state["showRoof"] if roof is None else roof
    return (f"House scene in {state['mode']} mode: living room extended {state['livingRoomExtraMeters']} m, "
            f"kitchen extended {state['kitchenExtraMeters']} m; roof {'shown' if roof else 'hidden'}, "
            f"room labels {'shown' if state['showRoomLabels'] else 'hidden'}, "
            f"layers {'exploded' if state['explodedLayers'] else 'assembled'}. "
            f"Centered door without stairs: {state['centeredDoorNoStairs']}; garage cars: {state['garageCars']}; "
            f"pool palms and flowers: {state['poolBackPalmsAndFlowers']}; "
            f"pool lounge chairs: {state['poolLoungeChairs']}.")


def note_content(project: object) -> str:
    project = validate(project)
    payload = json.dumps(project, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(payload.encode("utf-8")) > 16000:
        raise InvalidProject("project is too large")
    return f"{summary(project)}\n\n```nerva-workshop\n{payload}\n```"


def parse(body: str) -> dict | None:
    """None means ordinary note; an exact marker with bad data means corruption."""
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(FENCE.finditer(body))
    if not matches:
        if "```nerva-workshop" in body:
            raise InvalidProject("corrupt workshop project")
        return None
    if len(matches) != 1 or body.count("```nerva-workshop") != 1:
        raise InvalidProject("multiple workshop project blocks")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidProject("duplicate workshop project field")
            result[key] = value
        return result
    try:
        project = json.loads(matches[0].group(1), object_pairs_hook=unique_object)
    except (ValueError, TypeError) as exc:
        raise InvalidProject("corrupt workshop project JSON") from exc
    return validate(project)


def _eligible_paths(engine, cfg: dict) -> list[str]:
    graph = engine.build_real_brain_graph(cfg)
    if not graph.get("ok"):
        raise InvalidProject("vault index unavailable")
    marked = {node.get("relPath") for node in graph["nodes"]
              if node.get("workshopProject")}
    key = engine._cache_key(cfg)
    with engine._BRAIN_LOCK:
        records = dict(engine._BRAIN_CACHE["files"]) if engine._BRAIN_CACHE["key"] == key else {}
    return sorted(path for path, (source, _root, _parts) in records.items()
                  if source == engine.SOURCE_VAULT and path.lower().endswith(".md") and path in marked)


def list_projects(engine, cfg: dict) -> list[dict]:
    projects = []
    for path in _eligible_paths(engine, cfg):
        try:
            title, _tags, body, _links = engine.read_indexed_note(cfg, path)
            project = parse(body)
        except (OSError, ValueError):
            continue
        if project is not None:
            projects.append({"path": path, "title": title, "view": project["view"]})
    return projects


def get_project(engine, cfg: dict, path: str) -> dict:
    if not isinstance(path, str) or not path.lower().endswith(".md"):
        raise FileNotFoundError("workshop project not found")
    try:
        key = engine._cache_key(cfg)
    except ValueError:
        raise FileNotFoundError("workshop project not found") from None
    with engine._BRAIN_LOCK:
        found = engine._BRAIN_CACHE["files"].get(path) if engine._BRAIN_CACHE["key"] == key else None
    if found is None:
        engine.build_real_brain_graph(cfg)
        with engine._BRAIN_LOCK:
            found = engine._BRAIN_CACHE["files"].get(path) if engine._BRAIN_CACHE["key"] == key else None
    if found is None or found[0] != engine.SOURCE_VAULT:
        raise FileNotFoundError("workshop project not found")
    try:
        title, _tags, body, _links = engine._read_indexed_note_found(cfg, found)
    except (OSError, ValueError):
        raise FileNotFoundError("workshop project not found") from None
    project = parse(body)
    if project is None:
        raise FileNotFoundError("workshop project not found")
    return {"path": path, "title": title, "summary": summary(project), "project": project}


def save_project(engine, cfg: dict, title: str, project: object) -> dict:
    if (type(title) is not str or not title.strip() or len(title) > 120 or "```" in title
            or any(ord(ch) < 32 for ch in title)):
        raise InvalidProject("invalid project title")
    content = note_content(project)
    captured = engine.capture_inbox_note(cfg, title.strip(), content, [], reindex=False)
    path = captured["relPath"]
    try:
        reopened = get_project(engine, cfg, path)
    except (OSError, ValueError) as exc:
        raise SavedProjectUnavailable(path) from exc
    return {"path": path, "title": reopened["title"], "view": project["view"]}
