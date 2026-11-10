"""RB-2 — the whole hub, started under each spelling, comes up in the same posture.

``NERVA_<X>`` is the preferred spelling of every ``JARVIS_<X>``. A half-alias would fail
open: honour ``NERVA_HARDENED`` from the shell and ignore it in ``.env``, or read it in a
getter and miss it in an import-time read. So this file starts the real thing — a fresh
interpreter that imports ``agents.web`` (the import-time reads of the tokens, the rate
limit, CORS), runs the app's lifespan (the ``.env`` load, then every boot guard) and asks
the running app what posture it is in — once per spelling and per place a value can come
from, and compares the answers. It also measures that no hub variable is read before the
fold, and that a disagreement between the spellings stops the start by name.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agents")]
from agents.core import env_alias, env_config  # noqa: E402

pytestmark = pytest.mark.timeout(600)

ADMIN, USER, AUDIT = "boot-admin-token-4c81e0", "boot-user-token-90b2d7", "boot-audit-key-6e15aa"

_PROBE = r"""
import json, os, sys
reads = []
original = os._Environ.__getitem__
def spy(self, key):
    reads.append(key)
    return original(self, key)
os._Environ.__getitem__ = spy
import agents.core.env_alias as env_alias
real_normalize = env_alias.normalize_process_env
before_fold = [key for key in reads if isinstance(key, str)]
os._Environ.__getitem__ = original
# A boot guard's SystemExit comes out of the lifespan's task group as a cancellation: note
# the refusal where it is raised (the real guard, in the real lifespan), then let it go.
refusal = {}
def noting(function):
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except SystemExit as exc:
            refusal.setdefault("message", str(exc))
            raise
    return wrapped
try:
    import agents.web as web
    import importlib
    for name in ("agents.core.boot_guards", "core.boot_guards"):      # the hub imports it under both names
        module = importlib.import_module(name)
        module.enforce_boot_posture = noting(module.enforce_boot_posture)
    for name in ("agents.core.env_provenance", "core.env_provenance"):
        module = importlib.import_module(name)
        module.load_hub_env = noting(module.load_hub_env)
    from fastapi.testclient import TestClient
    with TestClient(web.app) as client:
        from agents.core import env_config, env_provenance as ep, http_client, paths, proxy_trust, safe_mode
        from agents.core.environments import scrub_child_env
        from agents.core.mcp.client import stdio_env_baseline
        from agents.core.security import hardened
        headers = {"X-Admin-Token": os.environ.get("PROBE_TOKEN", "")}
        env_reply = client.get("/api/admin/env", headers=headers)
        sources = client.get("/api/admin/env/sources", headers=headers)
        hub = lambda mapping: {k: v for k, v in mapping.items() if k.startswith(("JARVIS_", "NERVA_", "_NERVA"))}
        out = {
            "hardened": hardened.enabled(), "posture": hardened.posture(),
            "strict_egress": http_client.strict_egress_enabled(),
            "safe_mode": safe_mode.enabled(),
            "trusted_proxies": [str(net) for net in proxy_trust.trusted_proxies()],
            "admin_active": web._env_admin_active(), "user_active": web._env_user_active(),
            "admin_ok": web._admin_credential_ok(os.environ.get("PROBE_TOKEN", "")),
            "wrong_admin_ok": web._admin_credential_ok("not-the-token"),
            "anonymous_admin": client.get("/api/admin/env").status_code,
            "data_root": str(paths.data_root()), "user_home": str(paths.user_home()),
            "port": env_config.env_int("JARVIS_PORT", 0), "rate_limit": web.RATE_LIMIT_PER_MIN,
            "host": env_config.env_str("JARVIS_HOST", ""),
            "insecure_bind_ack": env_config.env_flag("JARVIS_ALLOW_INSECURE_BIND"),
            "direct": {k: os.environ.get(k) for k in sorted(os.environ) if k.startswith("JARVIS_")
                       and k not in ("JARVIS_USER_HOME", "JARVIS_HOME")},
            "new_spelling_left": sorted(k for k in os.environ if k.startswith("NERVA_")
                                        and env_config.other_spelling(k)),
            "child": hub(scrub_child_env(dict(os.environ))),
            "mcp_child": hub(stdio_env_baseline(dict(os.environ))),
            "env_route": env_reply.json() if env_reply.status_code == 200 else env_reply.status_code,
            "sources": {row["key"]: row for row in sources.json()["sources"]
                        if row["key"].startswith(("JARVIS_", "NERVA_", "_NERVA"))}
                       if sources.status_code == 200 else sources.status_code,
            "before_fold": before_fold,
        }
except BaseException as exc:
    if not refusal:
        raise
    print("@@RB2-REFUSED@@" + json.dumps({"type": "SystemExit", "message": refusal["message"]}))
    sys.stdout.flush()
    os._exit(0)
print("@@RB2-PROBE@@" + json.dumps(out))
"""


def _boot(tmp_path: Path, shell: dict[str, str], dotenv: str | None = None, *, home_spelling: str = "JARVIS",
          label: str = "run") -> dict:
    """Start the hub in a fresh interpreter. *shell* is its process environment; *dotenv*
    is the text of the data-home ``.env`` (the layer a packaged install configures)."""
    work = tmp_path / label
    data, home = work / "data", work / "home"
    home.mkdir(parents=True)
    if dotenv is not None:
        (home / ".env").write_text(dotenv, encoding="utf-8")
    env = {key: value for key, value in os.environ.items()
           if not env_config.other_spelling(key) and key != env_alias.MARKER
           and key not in ("DEV_MODE", "NERVA_PUBLIC_PROFILE", "NERVA_WORKSPACE")}
    env.update({f"{home_spelling}_HOME": str(data), f"{home_spelling}_USER_HOME": str(home),
                "PYTHONDONTWRITEBYTECODE": "1", "JARVIS_TESTING": "1", "PROBE_TOKEN": ADMIN})
    env.update(shell)
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=ROOT, env=env, capture_output=True, text=True,
                         timeout=300)
    assert out.returncode == 0, out.stderr[-4000:]
    for marker in ("@@RB2-PROBE@@", "@@RB2-REFUSED@@"):
        if marker in out.stdout:
            result = json.loads(out.stdout.rsplit(marker, 1)[1].splitlines()[0])
            result["refused"] = marker == "@@RB2-REFUSED@@"
            # what the process itself said: everything but the probe's own answer line
            result["output"] = out.stdout.rsplit(marker, 1)[0] + out.stderr
            result["roots"] = (str(data), str(home))
            return result
    raise AssertionError(out.stdout[-2000:] + out.stderr[-2000:])


def _comparable(result: dict) -> dict:
    """What must be equal between two spellings: everything the hub does. Left out: the
    account of which spelling was used (that is the one thing that differs), the paths of
    this run's own temporary roots, and the raw output."""
    data, home = result["roots"]

    def scrub(value):
        if isinstance(value, str):
            return value.replace(data, "<data>").replace(home, "<home>")
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    kept = {key: value for key, value in result.items() if key not in ("output", "roots", "sources", "before_fold")}
    kept["sources"] = {key: {field: item for field, item in row.items() if field not in ("spelling", "deprecated")}
                       for key, row in result["sources"].items()}
    kept["env_route"] = {key: value for key, value in result["env_route"].items()
                         if key.startswith("JARVIS_") or key.startswith("NERVA_")}
    return scrub(kept)


# The hardened box: every protection the brief names, switched on.
HARDENED_BOX = {
    "HARDENED": "1", "AUDIT_KEY": AUDIT, "ADMIN_TOKEN": ADMIN, "USER_TOKEN": USER,
    "TRUSTED_PROXIES": "127.0.0.1/32", "SAFE_MODE": "1", "STRICT_EGRESS": "0",
    "HOST": "0.0.0.0", "PORT": "8123", "RATE_LIMIT": "77",
}
# The opposite corner: the two switches that LOWER a protection when set.
OPEN_BOX = {"STRICT_EGRESS": "0", "HOST": "0.0.0.0", "ALLOW_INSECURE_BIND": "1", "PORT": "8124"}


def _spelled(prefix: str, box: dict[str, str]) -> dict[str, str]:
    return {f"{prefix}_{suffix}": value for suffix, value in box.items()}


def _as_dotenv(prefix: str, box: dict[str, str]) -> str:
    return "".join(f"{name}={value}\n" for name, value in _spelled(prefix, box).items())


def test_the_hardened_box_is_the_same_box_under_either_spelling_from_the_process_environment(tmp_path):
    old = _boot(tmp_path, _spelled("JARVIS", HARDENED_BOX), label="old")
    new = _boot(tmp_path, _spelled("NERVA", HARDENED_BOX), home_spelling="NERVA", label="new")
    assert not old["refused"] and not new["refused"], new.get("message") or old.get("message")
    # not vacuous: the protections are on
    assert new["hardened"] is True and new["strict_egress"] is True and new["safe_mode"] is True
    assert new["posture"]["audit_key_present"] is True and new["trusted_proxies"] == ["127.0.0.1/32"]
    assert new["admin_active"] and new["user_active"] and new["admin_ok"] and not new["wrong_admin_ok"]
    assert new["anonymous_admin"] in (401, 403)
    assert new["port"] == 8123 and new["rate_limit"] == 77 and new["host"] == "0.0.0.0"
    assert new["data_root"] == new["roots"][0] and new["user_home"] == new["roots"][1]   # NERVA_HOME / NERVA_USER_HOME
    assert _comparable(new) == _comparable(old)
    # the environment the hub and its children see is the JARVIS_ one, exactly
    assert new["new_spelling_left"] == [] and new["direct"]["JARVIS_HARDENED"] == "1"
    assert set(new["child"]) == {"JARVIS_HOME"} and new["mcp_child"] == old["mcp_child"]
    assert not [key for key in new["mcp_child"] if "TOKEN" in key or "KEY" in key or key.startswith(("NERVA", "_"))]
    # /api/admin/env masks the credentials under the name the hub reads
    for name, secret in (("JARVIS_ADMIN_TOKEN", ADMIN), ("JARVIS_USER_TOKEN", USER), ("JARVIS_AUDIT_KEY", AUDIT)):
        assert new["env_route"][name] != secret and secret not in json.dumps(new["env_route"])
        assert new["sources"][name]["masked"] is True and new["sources"][name]["layer"] == "process"
        assert new["sources"][name]["deprecated"] is False and old["sources"][name]["deprecated"] is True
        assert new["sources"][name]["spelling"] == "NERVA_" + name[len("JARVIS_"):]
    assert env_alias.MARKER not in new["env_route"] and env_alias.MARKER not in new["sources"]
    for secret in (ADMIN, USER, AUDIT):
        assert secret not in new["output"].replace(json.dumps(new["env_route"]), "")
        assert secret not in new["output"] and secret not in old["output"]

def test_the_hardened_box_is_the_same_box_under_either_spelling_from_a_dotenv_file(tmp_path):
    """The fail-open case RB-2 names: NERVA_HARDENED=1 in a .env must harden."""
    old = _boot(tmp_path, {}, _as_dotenv("JARVIS", HARDENED_BOX), label="old")
    new = _boot(tmp_path, {}, _as_dotenv("NERVA", HARDENED_BOX), home_spelling="NERVA", label="new")
    assert not old["refused"] and not new["refused"], new.get("message") or old.get("message")
    assert new["hardened"] is True and new["strict_egress"] is True and new["safe_mode"] is True
    assert new["posture"]["audit_key_present"] is True and new["trusted_proxies"] == ["127.0.0.1/32"]
    assert new["admin_active"] and new["user_active"] and new["admin_ok"] and not new["wrong_admin_ok"]
    assert new["anonymous_admin"] in (401, 403) and new["port"] == 8123
    assert new["rate_limit"] != 77          # read while the hub is imported: a .env value is not in effect …
    assert new["sources"]["JARVIS_RATE_LIMIT"]["note"] == old["sources"]["JARVIS_RATE_LIMIT"]["note"] != ""
    assert _comparable(new) == _comparable(old)
    assert new["new_spelling_left"] == []
    for name in ("JARVIS_HARDENED", "JARVIS_ADMIN_TOKEN", "JARVIS_SAFE_MODE", "JARVIS_TRUSTED_PROXIES"):
        assert new["sources"][name]["layer"] == "user_env" and new["sources"][name]["deprecated"] is False
        assert old["sources"][name]["layer"] == "user_env" and old["sources"][name]["deprecated"] is True


def test_the_switches_that_lower_a_protection_do_no_more_under_the_new_spelling(tmp_path):
    old = _boot(tmp_path, _spelled("JARVIS", OPEN_BOX), label="old")
    new = _boot(tmp_path, {}, _as_dotenv("NERVA", OPEN_BOX), label="new")
    assert not old["refused"] and not new["refused"], new.get("message") or old.get("message")
    for result in (old, new):
        assert result["hardened"] is False and result["strict_egress"] is False
        assert result["insecure_bind_ack"] is True and result["safe_mode"] is False
        assert result["admin_active"] is False and result["trusted_proxies"] == []
    # and without the acknowledgement the open bind is refused, whoever spells the host
    for label, shell, dotenv in (("p-old", {"JARVIS_HOST": "0.0.0.0"}, None), ("p-new", {"NERVA_HOST": "0.0.0.0"}, None),
                                 ("f-new", {}, "NERVA_HOST=0.0.0.0\n"),
                                 ("typo", {"NERVA_HOST": "0.0.0.0"}, "NERVA_ALLOW_INSECURE_BIND=ture\n")):
        refused = _boot(tmp_path, shell, dotenv, label=label)
        assert refused["refused"] and "Refusing to bind to non-loopback host" in refused["message"], label


@pytest.mark.parametrize("shell, dotenv, named", [
    ({"NERVA_HARDENED": "1"}, None, "JARVIS_AUDIT_KEY"),                         # hardened with no audit key
    ({}, "NERVA_HARDENED=1\n", "JARVIS_AUDIT_KEY"),
    ({"NERVA_CHANNEL_OPEN": "yse"}, None, "NERVA_CHANNEL_OPEN"),                 # the parse guard
    ({}, "NERVA_CHANNEL_PAIRING=offf\n", "NERVA_CHANNEL_PAIRING"),
    ({}, "NERVA_TASK_MEDIATION=enfroce\n", "JARVIS_TASK_MEDIATION"),
    ({"NERVA_TRUSTED_PROXIES": "*"}, None, "JARVIS_TRUSTED_PROXIES"),
    ({}, "NERVA_TRUSTED_PROXIES=0.0.0.0/0\n", "JARVIS_TRUSTED_PROXIES"),
    ({}, "TELEGRAM_BOT_TOKEN=123:abc\nNERVA_CHANNEL_PAIRING=0\n", "telegram bot"),
])
def test_what_refused_the_old_spelling_refuses_the_new_one(tmp_path, shell, dotenv, named):
    new = _boot(tmp_path, shell, dotenv, label="new")
    assert new["refused"] and new["type"] == "SystemExit" and named in new["message"], new.get("message")
    old = _boot(tmp_path, {key.replace("NERVA_", "JARVIS_", 1): value for key, value in shell.items()},
                dotenv.replace("NERVA_", "JARVIS_") if dotenv else None, label="old")
    assert old["refused"]
    assert old["message"].replace("JARVIS_CHANNEL", "NERVA_CHANNEL") == new["message"].replace("JARVIS_CHANNEL", "NERVA_CHANNEL")


@pytest.mark.parametrize("suffix, new_value, old_value", [
    ("HARDENED", "0", "1"), ("STRICT_EGRESS", "0", "1"), ("ALLOW_INSECURE_BIND", "1", "0"),
    ("ADMIN_TOKEN", "one-admin-token-aa11", "another-admin-token-bb22"),
    ("USER_TOKEN", "one-user-token-aa11", "another-user-token-bb22"),
    ("TRUSTED_PROXIES", "10.0.0.1/32", "127.0.0.1/32"), ("SAFE_MODE", "0", "1"),
])
def test_a_disagreement_stops_the_start_by_name_from_either_place(tmp_path, suffix, new_value, old_value):
    in_shell = _boot(tmp_path, {f"NERVA_{suffix}": new_value, f"JARVIS_{suffix}": old_value}, label="shell")
    in_file = _boot(tmp_path, {}, f"JARVIS_{suffix}={old_value}\nNERVA_{suffix}={new_value}\n", label="file")
    for result, where in ((in_shell, "the process environment"), (in_file, "the data-home .env")):
        assert result["refused"] and result["type"] == "SystemExit", result.get("message")
        assert f"NERVA_{suffix} / JARVIS_{suffix}" in result["message"] and where in result["message"]
        if len(new_value) > 4:                               # a secret: nowhere in what the process said
            assert new_value not in result["output"] and old_value not in result["output"]
    # … and across the two places it is not a disagreement at all: the process value stands
    admin = old_value if suffix == "ADMIN_TOKEN" else ADMIN
    layered = _boot(tmp_path, {"JARVIS_ADMIN_TOKEN": admin, "PROBE_TOKEN": admin, "JARVIS_AUDIT_KEY": AUDIT,
                               f"JARVIS_{suffix}": old_value},
                    f"NERVA_{suffix}={new_value}\n", label="layered")
    assert not layered["refused"], layered.get("message")
    assert layered["direct"][f"JARVIS_{suffix}"] == old_value and layered["new_spelling_left"] == []
    assert layered["sources"][f"JARVIS_{suffix}"]["layer"] == "process"
    assert layered["sources"][f"JARVIS_{suffix}"]["shadowed"] == ["user_env"]


def test_a_roots_disagreement_stops_the_start(tmp_path):
    for suffix in ("HOME", "USER_HOME"):
        other = str(tmp_path / "somewhere-else")
        result = _boot(tmp_path, {f"NERVA_{suffix}": other}, label=suffix)      # JARVIS_<suffix> is the run's own
        assert result["refused"] and f"NERVA_{suffix} / JARVIS_{suffix}" in result["message"]
        assert other not in result["message"]


def test_an_ordinary_knob_set_twice_starts_on_the_new_spelling_with_one_warning(tmp_path):
    result = _boot(tmp_path, {"NERVA_PORT": "8201", "JARVIS_PORT": "8202"},
                   "NERVA_LOG_LEVEL=warning\nJARVIS_LOG_LEVEL=info\n", label="knob")
    assert not result["refused"], result.get("message")
    assert result["port"] == 8201 and result["direct"]["JARVIS_LOG_LEVEL"] == "warning"
    assert result["output"].count("NERVA_PORT and JARVIS_PORT are both set") == 1
    assert result["output"].count("NERVA_LOG_LEVEL and JARVIS_LOG_LEVEL are both set") == 1


def test_no_hub_variable_is_read_before_the_fold(tmp_path):
    """The proof the design rests on: from the first statement of a fresh interpreter to
    the end of the fold, the only reads of the environment are the fold's own."""
    result = _boot(tmp_path, {"NERVA_HARDENED": "0", "NERVA_PORT": "8203"}, label="spy")
    assert not result["refused"], result.get("message")
    before = set(result["before_fold"])
    # the fold reads the NERVA_ spellings it folds and their JARVIS_ twins — nothing else of the hub's
    folded = {"NERVA_HARDENED", "NERVA_PORT", "NERVA_HOME", "NERVA_USER_HOME"}
    own = {key for key in before if key.startswith(("JARVIS_", "NERVA_")) or key in ("DEV_MODE",)}
    assert own <= folded | {env_alias.canonical(key) for key in folded} | {env_alias.MARKER}, sorted(own)
    assert result["direct"]["JARVIS_HARDENED"] == "0" and result["port"] == 8203


def test_the_fold_runs_first_in_every_entry_point():
    """serve.py, the coordinator, the supervisor, `agents.run`, the two CLI entries and the
    stdio MCP server all import the ``agents`` package before they read a hub variable;
    the only earlier touch of the environment is the --safe-mode switch, which is a write."""
    from scripts import doctor

    for script in ("serve.py", "scripts/coordinator.py", "scripts/nerva.py", "scripts/nerva_mcp_stdio.py",
                   "agents/run.py", "agents/cli/__main__.py", "scripts/install_smoke.py", "scripts/doctor.py"):
        path = ROOT / script
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        first_import = next((number for number, line in enumerate(lines)
                             if line.lstrip().startswith(("from agents", "import agents", "from scripts import", "from ."))), None)
        assert first_import is not None, script
        head = "\n".join(line for line in lines[:first_import] if "os.environ.update(" not in line
                         and "os.environ.pop(" not in line)
        early = {name for name in doctor.names_read_in(head) if name.startswith(("JARVIS_", "NERVA_"))}
        if script == "scripts/doctor.py":
            continue                      # reads through run_doctor(), which folds first (_canonical_env)
        assert early == set(), f"{script} reads {sorted(early)} before it imports the hub"
    doctor_source = (ROOT / "scripts/doctor.py").read_text(encoding="utf-8")
    assert "env = _canonical_env(env)" in doctor_source.split("def run_doctor(")[1].split("checks = [")[0]
    for script in ("scripts/release_gate.py", "scripts/soak_report.py", "scripts/export_partner_feedback.py",
                   "scripts/runtime_supervisor.py"):
        assert "import agents.core  # noqa" in (ROOT / script).read_text(encoding="utf-8"), script


def test_a_standalone_script_sees_the_new_spelling(tmp_path):
    """The scripts that read a hub variable without starting the hub fold first too."""
    env = {key: value for key, value in os.environ.items() if not env_config.other_spelling(key)}
    env.update({"NERVA_EVAL_STORE": str(tmp_path / "evals"), "NERVA_HOME": str(tmp_path / "data"),
                "NERVA_RUNTIME_RESPAWN_DELAY": "2.5", "PYTHONDONTWRITEBYTECODE": "1"})
    code = ("import os, sys\nsys.path.insert(0, 'scripts')\n"
            "import release_gate, export_partner_feedback, runtime_supervisor\n"
            "runtime_supervisor._accept_nerva_spellings()\n"
            "print(release_gate._eval_store_root()); print(export_partner_feedback.DATA_ROOT)\n"
            "print(os.environ.get('JARVIS_RUNTIME_RESPAWN_DELAY'))\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    store, data, delay = out.stdout.strip().splitlines()[-3:]
    assert store.startswith(str(tmp_path / "evals")) and data == str(tmp_path / "data") and delay == "2.5"
