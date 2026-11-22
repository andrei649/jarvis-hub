"""Small, validated parameter edits for the local 3D workshop."""

from __future__ import annotations

import json
import math
import re

from agents.core.llm.auxiliary_text import run_oneshot

SYSTEM = {
    "robot": (
        "Convert the user's robot appearance request into one JSON object only. "
        "Allowed keys: housingColor (\"silver\" or #RRGGBB), ringColor (#RRGGBB), "
        "shellColor (#RRGGBB). Use only requested changes. No prose, markdown, "
        "tools, files, or commands. Return {} if the request cannot be represented."
    ),
    "house": (
        "Convert the user's house request into one JSON object only. Allowed keys: "
        "enlargeLivingRoom (nonzero width change in metres, -5 to 5), "
        "enlargeKitchen (nonzero width change in metres, -4 to 4), "
        "addGarageCars, addPoolPalmsAndFlowers, addLoungeChairs, "
        "centerDoorRemoveStairs (true only), explodedHouse, showLabels, showRoof "
        "(booleans; showRoof is an absolute desired state). Use only requested changes. "
        "No prose, markdown, tools, files, or commands. Return {} if the request "
        "cannot be represented."
    ),
}
_ROBOT = {"housingColor", "ringColor", "shellColor"}
_HOUSE_NUMBERS = {"enlargeLivingRoom": 5, "enlargeKitchen": 4}
_HOUSE_TRUE = {"addGarageCars", "addPoolPalmsAndFlowers", "addLoungeChairs", "centerDoorRemoveStairs"}
_HOUSE_BOOL = {"explodedHouse", "showLabels", "showRoof"}
_HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")
_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```\Z", re.DOTALL | re.IGNORECASE)


class InvalidEdit(ValueError):
    """The model response cannot safely become workshop parameters."""


async def propose(router, view: str, instruction: str) -> dict:
    answer = await run_oneshot(router, instruction, system=SYSTEM[view], purpose="workshop_edit",
                               max_tokens=256, temperature=0, private_direct=True)
    if not isinstance(answer, str) or len(answer) > 4096:
        raise InvalidEdit("invalid workshop edit")
    raw = answer.strip()
    fenced = _FENCE.fullmatch(raw)
    if fenced:
        raw = fenced.group(1)
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidEdit("invalid workshop edit") from exc
    if type(params) is not dict or not params:
        raise InvalidEdit("unsupported workshop edit")

    if view == "robot":
        if set(params) - _ROBOT:
            raise InvalidEdit("invalid robot edit")
        for key, value in params.items():
            if key == "housingColor" and value == "silver":
                continue
            if type(value) is not str or not _HEX.fullmatch(value):
                raise InvalidEdit("invalid robot color")
    elif set(params) - (_HOUSE_NUMBERS.keys() | _HOUSE_TRUE | _HOUSE_BOOL):
        raise InvalidEdit("invalid house edit")
    else:
        for key, value in params.items():
            if key in _HOUSE_NUMBERS:
                limit = _HOUSE_NUMBERS[key]
                if type(value) not in (int, float) or not 0 < abs(value) <= limit or not math.isfinite(value):
                    raise InvalidEdit("invalid house width change")
            elif key in _HOUSE_TRUE and value is not True:
                raise InvalidEdit("invalid house addition")
            elif key in _HOUSE_BOOL and type(value) is not bool:
                raise InvalidEdit("invalid house toggle")
    return params
