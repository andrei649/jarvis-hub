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


# ── op-visual-grounding: coordinate conventions + rect/center-aware fusion ───

import pytest  # noqa: E402

from agents.core.screen_grounding import (  # noqa: E402
    CONVENTIONS,
    normalize_coords,
    normalize_point,
    resized_dims,
)


def test_conventions_are_the_four_named_ones():
    assert set(CONVENTIONS) == {"absolute", "absolute_resized", "relative_1000", "relative_unit"}


@pytest.mark.parametrize(
    "convention, emitted, expected",
    [
        ("absolute", (1000, 250), (1000, 250)),
        ("absolute_resized", (500, 125), (1000, 250)),   # model saw 1000×500
        ("relative_1000", (500, 250), (1000, 250)),
        ("relative_unit", (0.5, 0.25), (1000, 250)),
    ],
)
def test_normalize_point_round_trips_each_convention(convention, emitted, expected):
    out = normalize_point(*emitted, convention=convention, image_size=(2000, 1000),
                          resized_size=(1000, 500))
    assert out == expected


def test_normalize_point_clamps_overshoot_into_the_image():
    assert normalize_point(2100, -5, convention="absolute", image_size=(2000, 1000)) == (1999, 0)
    assert normalize_point(1000, 1000, convention="relative_1000", image_size=(200, 100)) == (199, 99)


def test_normalize_point_refuses_bad_inputs_instead_of_guessing():
    with pytest.raises(ValueError, match="convention"):
        normalize_point(1, 1, convention="pixels", image_size=(10, 10))
    with pytest.raises(ValueError, match="resized_size"):
        normalize_point(1, 1, convention="absolute_resized", image_size=(10, 10))
    with pytest.raises(ValueError, match="image_size"):
        normalize_point(1, 1, convention="absolute", image_size=(0, 10))
    with pytest.raises(ValueError, match="numeric"):
        normalize_point("a", 1, convention="absolute", image_size=(10, 10))
    with pytest.raises(ValueError, match="finite"):
        normalize_point(float("nan"), 1, convention="absolute", image_size=(10, 10))


def test_resized_dims_mirror_the_vlm_downscale():
    assert resized_dims((2000, 1000), 1024) == (1024, 512)
    assert resized_dims((800, 600), 1024) == (800, 600)   # already fits → untouched
    assert resized_dims({"width": 4000, "height": 1000}, 1000) == (1000, 250)


def test_normalize_coords_converts_points_and_rects_and_annotates():
    elements = [
        {"label": "Save", "x": 500, "y": 250, "source": "vlm",
         "rect": {"left": 400, "top": 200, "width": 200, "height": 100}},
        {"label": "no coords"},
        {"label": "bad", "x": "??", "y": 1},
    ]
    out = normalize_coords(elements, convention="relative_1000", image_size=(2000, 1000))
    assert len(out) == 1
    save = out[0]
    assert (save["x"], save["y"]) == (1000, 250)
    assert save["rect"] == {"left": 800, "top": 200, "width": 400, "height": 100}
    assert save["convention"] == "absolute"
    assert save["emitted_convention"] == "relative_1000"
    assert elements[0]["x"] == 500  # input untouched


def test_normalize_coords_rejects_unknown_convention():
    with pytest.raises(ValueError):
        normalize_coords([], convention="mystery", image_size=(1, 1))


def test_parse_grounding_understands_box_forms_and_carries_rect():
    # OS-Atlas / Qwen box in free text → centre point + rect
    out = parse_grounding("Submit [100, 200, 140, 220]")
    assert out == [{"label": "Submit", "x": 120, "y": 210,
                    "rect": {"left": 100, "top": 200, "width": 40, "height": 20},
                    "source": "vlm"}]
    # marker-wrapped double bracket form, no label
    out = parse_grounding("<|box_start|>[[10,20,30,40]]<|box_end|>")
    assert (out[0]["x"], out[0]["y"]) == (20, 30) and out[0]["label"] == ""
    # Qwen JSON bbox_2d / point_2d, single object or list
    out = parse_grounding('{"bbox_2d": [0, 0, 10, 10], "label": "OK"}')
    assert out[0]["label"] == "OK" and (out[0]["x"], out[0]["y"]) == (5, 5)
    out = parse_grounding('[{"point_2d": [7, 9], "label": "Cancel"}]')
    assert out == [{"label": "Cancel", "x": 7, "y": 9, "source": "vlm"}]
    # the historical point form still wins and stays rect-free
    assert "rect" not in parse_grounding("Save at (12,24)")[0]


def test_fuse_with_a11y_uses_rect_and_center_from_driver_elements():
    grounded = [{"label": "Save", "x": 120, "y": 340, "source": "vlm"}]
    a11y = [
        # rect containing the grounded point, far beyond the 24px tolerance from centre
        {"name": "Save file", "role": "Button",
         "rect": {"left": 50, "top": 300, "width": 300, "height": 80}},
        # centre-only node → appended as a11y with its click point
        {"name": "Menu", "role": "Menu", "center": [10, 10]},
        # rect-only node → click point is the rect centre
        {"name": "Close", "role": "Button", "rect": [900, 0, 20, 20]},
        # node without any geometry → skipped
        {"name": "Ghost", "role": "Text"},
    ]
    fused = fuse_with_a11y(grounded, a11y)
    save = next(e for e in fused if e["x"] == 120)
    assert save["source"] == "fused" and save["a11y_label"] == "Save file"
    assert save["rect"] == {"left": 50, "top": 300, "width": 300, "height": 80}
    menu = next(e for e in fused if e["label"] == "Menu")
    assert (menu["x"], menu["y"]) == (10, 10) and menu["source"] == "a11y"
    close = next(e for e in fused if e["label"] == "Close")
    assert (close["x"], close["y"]) == (910, 10)
    assert close["rect"] == {"left": 900, "top": 0, "width": 20, "height": 20}
    assert not any(e.get("label") == "Ghost" for e in fused)
    assert locate(fused, "save file")["source"] == "fused"
