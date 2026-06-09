"""H15.2 — Local screen understanding (UI grounding + a11y fusion). Offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.screen_grounding import (
    parse_grounding, fuse_with_a11y, locate, ScreenGrounding,
)


def test_parse_grounding_json():
    out = parse_grounding('[{"label": "Submit", "x": 120, "y": 340}]')
    assert out == [{"label": "Submit", "x": 120, "y": 340, "source": "vlm"}]


def test_parse_grounding_freetext():
    out = parse_grounding("The Submit button at (120, 340) and Cancel at (50, 60)")
    coords = {(e["x"], e["y"]) for e in out}
    assert (120, 340) in coords and (50, 60) in coords


def test_fuse_with_a11y_dedups_and_adds():
    grounded = [{"label": "Submit", "x": 120, "y": 340, "source": "vlm"}]
    a11y = [{"label": "Submit button", "role": "button", "x": 122, "y": 341},  # close → merge
            {"label": "Menu", "role": "menu", "x": 10, "y": 10}]               # new → add
    fused = fuse_with_a11y(grounded, a11y)
    submit = next(e for e in fused if e["x"] == 120)
    assert submit["source"] == "fused" and submit["role"] == "button"
    assert any(e["source"] == "a11y" and e["label"] == "Menu" for e in fused)


def test_locate_by_query():
    elements = [{"label": "Submit", "x": 1, "y": 1}, {"label": "Cancel", "x": 2, "y": 2}]
    assert locate(elements, "cancel")["x"] == 2
    assert locate(elements, "nope") is None


def test_screen_grounding_end_to_end():
    sg = ScreenGrounding()
    elements = sg.ground('[{"label":"OK","x":5,"y":5}]', a11y=[{"label": "OK btn", "x": 6, "y": 6}])
    assert sg.locate(elements, "ok")["source"] == "fused"
