"""H214 + H238 + H590 — Petdex, Hatch-a-Pet, reactive agent-state companions & terminal sprites."""

from __future__ import annotations

import base64
import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.cli.nerva import Context
from agents.cli.nerva import main as nerva_main
from agents.core import settings_db
from agents.core.commands import CommandContext, Principal, build_default_registry
from agents.core.pets import (
    AGENT_STATES,
    PetError,
    PetStore,
    derive_agent_state,
    encode_rgba_png,
    render_halfblock,
    render_terminal_protocol,
)
from agents.core.routers import pets as pets_router
from agents.core.routers._deps import admin_guard, user_guard


@pytest.fixture
def isolated_pets(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    store = PetStore(tmp_path / "pets.json")
    return store


def test_h238_h590_petdex_agent_states_terminal_protocols_and_zip_roundtrip(isolated_pets):
    store = isolated_pets

    # 1. Built-in Petdex gallery has 6 species, each with 5 agent-state animations.
    gal = store.gallery()
    assert gal["ok"] is True
    assert len(gal["pets"]) == 6
    assert {p["id"] for p in gal["pets"]} == {
        "spark-owl",
        "circuit-fox",
        "nebula-cat",
        "forge-golem",
        "void-axolotl",
        "pixel-raven",
    }

    # 2. Live orchestrator state derivation across idle / thinking / tool / failing.
    assert derive_agent_state(None)["agent_state"] == "idle"
    assert derive_agent_state(SimpleNamespace(_turn_in_progress=True))["agent_state"] == "thinking"
    assert derive_agent_state(SimpleNamespace(_active_tool_name="web_search"))["agent_state"] == "tool"
    assert derive_agent_state(SimpleNamespace(_estop_active=True))["agent_state"] == "failing"

    for st in AGENT_STATES:
        cell_doc = store.cells("nebula-cat", state=st, frame=1)
        assert cell_doc["rows"] == 8 and cell_doc["cols"] == 8
        assert cell_doc["frame_count"] == 2

    # 3. Select, rename, scale, roam, overlay preferences + settings_db sync.
    sel = store.select("nebula-cat")
    assert sel["active_id"] == "nebula-cat"
    store.rename("nebula-cat", "Starlight")
    assert store.meta("nebula-cat")["pet"]["name"] == "Starlight"
    prefs = store.update_preferences(scale=1.75, roam=True, overlay_enabled=True)
    assert prefs["scale"] == 1.75
    assert prefs["roam"] is True
    assert prefs["overlay_enabled"] is True
    pets_cfg = {r["key"]: r["value"] for r in settings_db.get_category("pets")}
    assert pets_cfg["active_id"] == "nebula-cat"

    # Built-in species cannot be deleted; confirm=False also refuses.
    with pytest.raises(PetError) as exc_unconf:
        store.remove("nebula-cat", confirm=False)
    assert exc_unconf.value.reason == "confirm_required"
    with pytest.raises(PetError) as exc_builtin:
        store.remove("nebula-cat", confirm=True)
    assert exc_builtin.value.reason == "builtin_protected"

    # 4. Terminal renderers: half-block ANSI, NO_COLOR ASCII, Kitty graphics, iTerm2 inline PNG.
    grid = store.cells("spark-owl", state="thinking", frame=0)["cells"]
    hb = render_halfblock(grid, ansi=True)
    assert "▀" in hb and "\x1b[38;2;" in hb

    png_bytes = encode_rgba_png(grid, scale_px=4)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    kitty = render_terminal_protocol(grid, protocol="auto", env={"KITTY_WINDOW_ID": "1"})
    assert kitty["protocol"] == "kitty" and kitty["rendered"].startswith("\x1b_Ga=T,f=100")

    iterm = render_terminal_protocol(grid, protocol="auto", env={"TERM_PROGRAM": "iTerm.app"})
    assert iterm["protocol"] == "iterm2" and "\x1b]1337;File=inline=1" in iterm["rendered"]

    no_color = render_terminal_protocol(grid, protocol="auto", env={"NO_COLOR": "1"})
    assert no_color["protocol"] == "ascii" and "\x1b[" not in no_color["rendered"]

    # 5. Export `.pet.zip` + re-import + zip-slip rejection.
    fname, raw_zip = store.export_zip("nebula-cat")
    assert fname == "nebula-cat.pet.zip"
    imported = store.import_zip(raw_zip)
    custom_id = imported["pet"]["id"]
    assert imported["pet"]["builtin"] is False
    assert custom_id.startswith("custom-")

    # Malicious path traversal archive is rejected cleanly.
    evil_buf = io.BytesIO()
    with zipfile.ZipFile(evil_buf, "w") as zf:
        zf.writestr("../escape.txt", "nope")
    with pytest.raises(PetError) as exc_slip:
        store.import_zip(evil_buf.getvalue())
    assert exc_slip.value.reason == "unsafe_zip_path"

    # Confirmed deletion removes custom pet cleanly.
    removed = store.remove(custom_id, confirm=True)
    assert removed["removed"] == custom_id

    # 6. Doctor report passes all 4 subsystem checks.
    doc = store.doctor(env={"TERM": "xterm-256color"})
    assert doc["ok"] is True
    assert len(doc["checks"]) == 4


def test_h214_hatch_a_pet_drafts_confirmed_remix_cancel_and_adopt(isolated_pets):
    store = isolated_pets

    # Deferred generation transitions running -> completed on poll, and can be cancelled before hatch.
    deferred = store.generate_drafts("clockwork red panda", defer_completion=True)
    assert deferred["status"] == "running"
    assert deferred["drafts"] == []
    polled = store.generation_status(deferred["job_id"])
    assert polled["status"] == "completed"
    assert len(polled["drafts"]) == 4
    cancelled = store.cancel_generation(deferred["job_id"])
    assert cancelled["status"] == "cancelled"

    # Reference image tinting + confirmed remix + hatch adoption.
    ref_b64 = base64.b64encode(b"\x89PNG-synthetic-reference-seed").decode("ascii")
    job = store.generate_drafts(
        "bioluminescent deep-sea axolotl",
        image_backend="svg-synth",
        reference_image_b64=ref_b64,
    )
    assert job["has_reference_image"] is True
    assert len(job["drafts"]) == 4
    first_draft = job["drafts"][0]["draft_id"]

    # Remix without confirm=True is refused (409).
    with pytest.raises(PetError) as exc_remix:
        store.remix_draft(job["job_id"], first_draft, instruction="more neon", confirm=False)
    assert exc_remix.value.reason == "confirm_required"
    assert exc_remix.value.status == 409

    remixed = store.remix_draft(
        job["job_id"], first_draft, instruction="brighter neon gills", confirm=True
    )
    new_draft_id = remixed["remixed_draft_id"]
    assert any(d["draft_id"] == new_draft_id for d in remixed["drafts"])

    hatched = store.hatch_draft(job["job_id"], new_draft_id, name="Abyssal Pip", adopt_active=True)
    assert hatched["hatch_stage"] == "hatched"
    assert hatched["adopted"] is True
    assert hatched["pet"]["name"] == "Abyssal Pip"
    assert store.info()["active_id"] == hatched["pet"]["id"]


@pytest.mark.asyncio
async def test_pets_http_routes_slash_commands_and_cli(isolated_pets, monkeypatch):
    from agents import web

    orch = SimpleNamespace(pets=isolated_pets, _turn_in_progress=False, _estop_active=False)
    monkeypatch.setattr(web, "orch", orch)

    # 1. Slash commands `/pet` and `/hatch`.
    owner = Principal(channel="web", sender="owner", admin=True)
    reg = build_default_registry()
    info_txt = await reg.get("pet").handler(CommandContext(orch=orch, principal=owner, name="pet", args="info"))
    assert "Spark Owl" in info_txt
    hatch_txt = await reg.get("hatch").handler(
        CommandContext(orch=orch, principal=owner, name="hatch", args="miniature brass dragon")
    )
    assert "pgen_" in hatch_txt

    # 2. HTTP routes across all 17 endpoints.
    app = FastAPI()
    app.include_router(pets_router.router)
    app.dependency_overrides[user_guard] = lambda: None
    app.dependency_overrides[admin_guard] = lambda: None
    client = TestClient(app)

    assert client.get("/api/pets?state=thinking").json()["agent_state"] == "thinking"
    assert len(client.get("/api/pets/gallery").json()["pets"]) == 6
    assert client.get("/api/pets/doctor").json()["ok"] is True
    assert client.get("/api/pets/spark-owl/meta").json()["pet"]["id"] == "spark-owl"
    assert client.get("/api/pets/spark-owl/cells?state=tool&frame=1").json()["state"] == "tool"
    assert client.get("/api/pets/spark-owl/thumb?state=idle").json()["data_uri"].startswith("data:image/svg+xml")

    assert client.post("/api/pets/select", json={"pet_id": "circuit-fox"}).json()["active_id"] == "circuit-fox"
    assert client.put("/api/pets/preferences", json={"roam": True, "scale": 1.5}).json()["roam"] is True
    assert client.post("/api/pets/circuit-fox/rename", json={"name": "Copper"}).json()["pet"]["name"] == "Copper"

    exp = client.get("/api/pets/circuit-fox/export").json()
    imp = client.post("/api/pets/import", json={"zip_base64": exp["zip_base64"]}).json()
    imp_id = imp["pet"]["id"]

    gen = client.post("/api/pets/hatch/generate", json={"prompt": "starlight kitsune"}).json()
    jid = gen["job_id"]
    did = gen["drafts"][0]["draft_id"]
    assert client.get(f"/api/pets/hatch/jobs/{jid}").json()["status"] == "completed"

    # Unconfirmed HTTP remix returns 409; confirmed succeeds.
    assert client.post(f"/api/pets/hatch/jobs/{jid}/remix", json={"draft_id": did, "confirm": False}).status_code == 409
    rem = client.post(f"/api/pets/hatch/jobs/{jid}/remix", json={"draft_id": did, "confirm": True}).json()
    adopted = client.post(
        f"/api/pets/hatch/jobs/{jid}/adopt",
        json={"draft_id": rem["remixed_draft_id"], "name": "Kitsune"},
    ).json()
    assert adopted["pet"]["name"] == "Kitsune"

    gen2 = client.post("/api/pets/hatch/generate", json={"prompt": "cancel me"}).json()
    assert client.post(f"/api/pets/hatch/jobs/{gen2['job_id']}/cancel").json()["status"] == "cancelled"

    assert client.delete(f"/api/pets/{imp_id}?confirm=false").status_code == 409
    assert client.delete(f"/api/pets/{imp_id}?confirm=true").json()["removed"] == imp_id

    # 3. `nerva pets` CLI offline render & HTTP status dispatch.
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    cli_ctx = Context(
        out=out_buf,
        err=err_buf,
        environ={"NO_COLOR": "1"},
        client_factory=lambda _env: SimpleNamespace(
            request=lambda method, path, body=None: client.request(method, path, json=body).json()
        ),
    )
    monkeypatch.setattr("agents.cli.pets.PetStore", lambda: isolated_pets)
    assert nerva_main(["pets", "render", "--state", "idle", "--protocol", "ascii"], context=cli_ctx) == 0
    assert out_buf.getvalue().strip() != ""
    assert nerva_main(["pets", "gallery"], context=cli_ctx) == 0
