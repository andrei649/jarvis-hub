"""Tests for the AIS stream helpers (subscription + frame handling)."""

import pytest

from worldview_ingest.ais.stream import WORLD_BBOX, build_subscription, handle_frame
from worldview_ingest.config import Settings

POSITION_FRAME = (
    '{"MessageType":"PositionReport",'
    '"MetaData":{"MMSI":636092297,"latitude":26.5,"longitude":56.2,'
    '"time_utc":"2024-06-07 12:00:00.000 +0000 UTC"},'
    '"Message":{"PositionReport":{"Sog":12.3,"Cog":118.0,"TrueHeading":117}}}'
)


def test_build_subscription_requires_api_key():
    with pytest.raises(RuntimeError):
        build_subscription(Settings())  # no key configured


def test_build_subscription_defaults_to_world_bbox():
    sub = build_subscription(Settings(), api_key="k")
    assert sub["APIKey"] == "k"
    assert sub["BoundingBoxes"] == WORLD_BBOX
    assert sub["FilterMessageTypes"] == ["PositionReport"]


def test_build_subscription_parses_bbox():
    sub = build_subscription(Settings(ais_bbox="24,55,27,58"), api_key="k")
    assert sub["BoundingBoxes"] == [[[24.0, 55.0], [27.0, 58.0]]]


def test_build_subscription_rejects_bad_bbox():
    with pytest.raises(ValueError):
        build_subscription(Settings(ais_bbox="1,2,3"), api_key="k")


def test_handle_frame_position_report():
    env = handle_frame(POSITION_FRAME)
    assert env is not None
    assert env.domain == "ais"
    assert env.entity_id == "636092297"
    assert env.payload["sog_kt"] == 12.3


def test_handle_frame_ignores_non_position_and_malformed():
    assert handle_frame('{"MessageType":"ShipStaticData"}') is None
    assert handle_frame("not json") is None
    assert handle_frame("[1,2,3]") is None  # valid json, not a dict
