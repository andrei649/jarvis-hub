"""DRA-15 backend defect 6: four distinct mission refusals answered one 409 string.

`_transition` caught every MissionError and returned
{"error": "operation not allowed in current mission state"}. For `finish_step` that
covers FOUR different causes — mission gone, mission not active, step index out of
range, and an invalid step status — and for two of them the fixed message is not merely
vague but WRONG: "step 99 out of range" and "invalid step status: bogus" are not about
mission state at all. The HUD, reading that string, told the operator to "start or resume
the mission", advice that cannot be followed when the real problem is a bad index.

The exception text deliberately does NOT flow to the body (a user-traced value must not
reach the response sink), so the fix is a LITERAL code set at each raise site and mapped
to a fixed message — distinguishable causes with no interpolated data.
"""

import pytest

from agents.core.autonomy.missions import MissionError, MissionStore


@pytest.fixture
def store(tmp_path):
    return MissionStore(db_path=str(tmp_path / "missions.db")).initialize()


def _active_mission(store):
    m = store.create(title="t", plan=[{"text": "step one"}])
    store.start(m.id)
    return store.get(m.id)


def test_each_refusal_carries_its_own_code(store):
    m = _active_mission(store)

    with pytest.raises(MissionError) as e1:
        store.finish_step(99999, idx=0, status="done")
    assert e1.value.code == "mission_not_found"

    with pytest.raises(MissionError) as e2:
        store.finish_step(m.id, idx=42, status="done")
    assert e2.value.code == "step_out_of_range"

    with pytest.raises(MissionError) as e3:
        store.finish_step(m.id, idx=0, status="not-a-status")
    assert e3.value.code == "invalid_step_status"

    store.cancel(m.id)
    with pytest.raises(MissionError) as e4:
        store.finish_step(m.id, idx=0, status="done")
    assert e4.value.code == "mission_not_active"


def test_a_code_is_a_literal_and_never_carries_request_data(store):
    """The whole reason the body could not just echo str(e)."""
    m = _active_mission(store)
    with pytest.raises(MissionError) as e:
        store.finish_step(m.id, idx=4242, status="done")
    assert "4242" not in e.value.code
    assert str(m.id) not in e.value.code
    assert e.value.code == "step_out_of_range"


def test_an_illegal_transition_is_distinguishable_from_a_missing_mission(store):
    # CANCELLED is terminal — _TRANSITIONS gives it an empty exit set — so a start from
    # there is illegal while the mission plainly exists. (PLANNED -> ACTIVE is legal, so
    # resume on a fresh mission is NOT the illegal case; checked against the table.)
    m = _active_mission(store)
    store.cancel(m.id)
    with pytest.raises(MissionError) as e:
        store.start(m.id)
    assert e.value.code == "illegal_transition"
    # and it must not be mistaken for the mission being gone
    assert e.value.code != "mission_not_found"


def test_the_api_answers_a_distinct_message_per_cause(store, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    import agents.web as web

    m = _active_mission(store)
    monkeypatch.setattr(web, "orch", SimpleNamespace(missions=store))
    client = TestClient(web.app)

    bad_index = client.post(f"/api/missions/{m.id}/steps/4242/finish", json={})
    bad_status = client.post(f"/api/missions/{m.id}/steps/0/finish", json={"status": "bogus"})
    assert bad_index.status_code == 409 and bad_status.status_code == 409

    # the two causes must not answer the same string
    assert bad_index.json()["error"] != bad_status.json()["error"]
    assert bad_index.json()["code"] == "step_out_of_range"
    assert bad_status.json()["code"] == "invalid_step_status"
    # and neither may blame mission state, which is not the problem here
    assert "mission state" not in bad_index.json()["error"]
    assert "mission state" not in bad_status.json()["error"]
    # no request-supplied value reaches the body
    assert "4242" not in bad_index.text and "bogus" not in bad_status.text
