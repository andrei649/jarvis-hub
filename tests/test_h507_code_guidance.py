"""H507 — warn when code the agent writes contains a known-dangerous pattern.

A warn-only rule table (``agents/core/code_guidance.py``): unsafe deserialization,
command and code injection, SQL from an f-string, XSS sinks, crypto and TLS footguns,
XXE, a remote script without SRI, and ``${{ github.event.* }}`` inside a workflow
``run:``. Findings ride on the ``file_write`` approval card and write result and on a
skill install or generation; nothing is ever refused; ``security.code_guidance``
switches it off.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import code_guidance, settings_db  # noqa: E402
from agents.core.code_guidance import scan  # noqa: E402


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    monkeypatch.setattr(settings_db, "_wal_set", False)
    monkeypatch.delenv("JARVIS_ACTION_KERNEL", raising=False)


def _rules(path, text):
    return [f["rule"] for f in scan(path, text)]


def _incomplete(line):
    return {"rule": "scan-incomplete", "line": line, "message": code_guidance.INCOMPLETE_MESSAGE}


# ── the rules ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path,line,rule", [
    ("a.py", "data = pickle.load(open(p, 'rb'))", "py-pickle-load"),
    ("a.py", "obj = dill.loads(blob)", "py-pickle-load"),
    ("a.py", "m = marshal.loads(b)", "py-pickle-load"),
    ("a.py", "cfg = yaml.load(text)", "py-yaml-load"),
    ("a.py", "cfg = yaml.unsafe_load(text)", "py-yaml-load"),
    ("a.py", "w = torch.load(path)", "py-torch-load"),
    ("a.py", "os.system(cmd)", "py-os-system"),
    ("a.py", "f = os.popen(cmd)", "py-os-system"),
    ("a.py", "subprocess.run(cmd, shell=True)", "py-shell-true"),
    ("a.py", "value = eval(user_input)", "py-eval"),
    ("a.py", "exec(code)", "py-eval"),
    ("a.py", "cur.execute(f\"SELECT * FROM t WHERE id={x}\")", "py-sql-fstring"),
    ("a.py", "cur.execute(\"SELECT * FROM t WHERE id=%s\" % x)", "py-sql-fstring"),
    ("a.py", "name = tempfile.mktemp()", "py-mktemp"),
    ("a.py", "requests.get(url, verify=False)", "py-tls-verify-off"),
    ("a.py", "ctx = ssl._create_unverified_context()", "py-ssl-unverified"),
    ("a.py", "ctx.verify_mode = ssl.CERT_NONE", "py-ssl-unverified"),
    ("a.py", "p = etree.XMLParser(resolve_entities=True)", "py-xxe"),
    ("a.py", "h = hashlib.md5(password.encode())", "py-weak-hash-password"),
    ("a.py", "c = AES.new(k, AES.MODE_ECB)", "crypto-ecb"),
    ("a.js", "const x = eval(input)", "js-eval"),
    ("a.ts", "const f = new Function('a', body)", "js-new-function"),
    ("a.js", "child_process.exec(cmd)", "js-child-exec"),
    ("a.js", "execSync(`rm ${dir}`)", "js-child-exec"),
    ("a.js", "cp.execSync(cmd)", "js-child-exec"),                     # an aliased module too
    ("a.js", "el.innerHTML = userHtml", "js-inner-html"),
    ("a.tsx", "el.outerHTML += more", "js-inner-html"),
    ("a.js", "document.write(x)", "js-document-write"),
    ("a.jsx", "<div dangerouslySetInnerHTML={{__html: x}} />", "react-dangerous-html"),
    ("a.js", "const c = crypto.createCipher('aes192', pw)", "js-create-cipher"),
    ("a.js", "https.request({ rejectUnauthorized: false })", "js-tls-off"),
    ("run.sh", "export NODE_TLS_REJECT_UNAUTHORIZED=0", "js-tls-off"),
    ("a.js", "const c = crypto.createCipheriv('aes-128-ecb', k, null)", "crypto-ecb"),
    ("a.js", "parseXml(s, { noent: true })", "js-xxe"),
    ("a.go", 'cmd := exec.Command("sh", "-c", line)', "go-exec-shell"),
    ("a.go", 'cmd := exec.CommandContext(ctx, "/bin/bash", "-c", line)', "go-exec-shell"),
    ("a.go", "cfg := &tls.Config{InsecureSkipVerify: true}", "go-tls-insecure"),
    ("a.html", '<script src="https://cdn.example/lib.js"></script>', "html-script-no-sri"),
    ("a.html", "<script src='//cdn.example/lib.js'></script>", "html-script-no-sri"),
    ("a.html", "<script>document.write('x')</script>", "js-document-write"),
    # review-H507 F7/F8: a call over several lines, and the other spellings of a call
    ("a.py", "cur.execute(\n    f\"SELECT * FROM t WHERE id = {x}\"\n)", "py-sql-fstring"),
    ("a.py", "cfg = yaml.load(open(p))", "py-yaml-load"),
    ("a.py", "cfg = yaml.load(a); other(Loader=yaml.SafeLoader)", "py-yaml-load"),
    ("a.py", "w = torch.load(os.path.join(d, 'm.pt'))", "py-torch-load"),
    ("a.js", "require('child_process').exec(cmd)", "js-child-exec"),
    ("a.js", "const { exec } = require('child_process');\nexec(cmd)", "js-exec-imported"),
    ("a.mjs", "import { exec } from 'node:child_process';\nexec(`ls ${dir}`)", "js-exec-imported"),
    ("a.js", "const c = require('crypto').createCipher('aes192', pw)", "js-create-cipher"),
    ("a.js", "const c = nodeCrypto.createCipher('aes192', pw)", "js-create-cipher"),
])
def test_each_rule_fires(path, line, rule):
    assert rule in _rules(path, line)


@pytest.mark.parametrize("path,line", [
    ("a.py", "model.eval()"),                                  # a method, not the builtin
    ("a.py", "self.exec(query)"),
    ("a.py", "cfg = yaml.load(text, Loader=yaml.SafeLoader)"),
    ("a.py", "cfg = yaml.load(text, Loader=CSafeLoader)"),
    ("a.py", "cfg = yaml.safe_load(text)"),
    ("a.py", "w = torch.load(path, weights_only=True)"),
    ("a.py", "subprocess.run(['ls', '-l'])"),
    ("a.py", "shell = True_ish"),
    ("a.py", "cur.execute('SELECT 1 WHERE id = ?', (x,))"),
    ("a.py", "requests.get(url, verify=True)"),
    ("a.py", "# eval(x) mentioned in a comment"),
    ("a.py", "    # os.system('rm -rf /') is what we never do"),
    ("a.py", "h = hashlib.sha256(password.encode())"),
    ("a.py", "digest = hashlib.md5(data).hexdigest()"),             # a checksum, not a password
    ("a.js", "regex.exec(s)"),
    ("a.js", "obj.eval(x)"),
    ("a.js", "if (el.innerHTML === other) {}"),
    ("a.js", "el.textContent = userHtml"),
    ("a.js", "// eval(x) in a comment"),
    ("a.js", "const c = crypto.createCipheriv('aes-256-gcm', k, iv)"),
    ("a.go", 'cmd := exec.Command("git", "status")'),
    ("a.html", '<script src="https://cdn.example/lib.js" integrity="sha384-abc" crossorigin="anonymous"></script>'),
    ("a.html", '<script src="/static/app.js"></script>'),
    ("a.txt", "eval(x); pickle.load(f); os.system(c)"),     # not a code file
    ("a.md", "yaml.load(text)"),
    ("a.py", "a.js = 'eval(x)'" if False else "print('hello')"),
    # review-H507 F7/F8: the guard reads the whole call, nested and wrapped
    ("a.py", "cfg = yaml.load(open(p).read(), Loader=yaml.SafeLoader)"),
    ("a.py", "w = torch.load(os.path.join(d, 'm.pt'), weights_only=True)"),
    ("a.py", "w = torch.load(p, map_location=torch.device('cpu'), weights_only=True)"),
    ("a.py", "w = torch.load(\n    path,\n    weights_only=True,\n)"),
    ("a.py", "cfg = yaml.load(\n    fh,\n    Loader=yaml.SafeLoader,\n)"),
    ("a.py", "cur.execute(\"SELECT * FROM t WHERE id = ?\", (f\"{a}\",))"),
    ("a.py", "    def eval(self, x):"),
    ("a.py", "    async def exec(self, q):"),
    ("a.js", "exec(cmd)"),                                       # no child_process here
    ("a.js", "const cp = require('child_process');\nconst m = regex.exec(s)"),
    ("a.js", "const c = nodeCrypto.createCipheriv('aes-256-gcm', k, iv)"),
])
def test_the_guards_hold(path, line):
    assert _rules(path, line) == []


def test_js_rules_do_not_fire_in_python_and_the_reverse():
    assert _rules("a.py", "el.innerHTML = x") == []
    assert _rules("a.js", "subprocess.run(cmd, shell=True)") == []
    assert _rules("a.go", "value = eval(x)") == []


def test_findings_carry_the_line_and_a_message():
    found = scan("app/worker.PY", "import os\n\nos.system(cmd)\n")
    assert found == [{"rule": "py-os-system", "line": 3,
                      "message": next(r.message for r in code_guidance.RULES if r.id == "py-os-system")}]
    assert scan("x.py", "") == [] and scan("x.py", None) == []


def test_the_table_is_about_twenty_five_rules_with_unique_ids():
    ids = [r.id for r in code_guidance.RULES] + [code_guidance.WORKFLOW_RULE_ID]
    assert len(ids) == len(set(ids)) and 24 <= len(ids) <= 30
    assert all(r.exts and r.message for r in code_guidance.RULES)


# ── GitHub Actions ───────────────────────────────────────────────────────────────

WORKFLOW = """\
on: issues
jobs:
  triage:
    runs-on: ubuntu-latest
    steps:
      - run: echo "${{ github.event.issue.title }}"
      - name: safe
        if: ${{ github.event.issue.title != '' }}
        env:
          TITLE: ${{ github.event.issue.title }}
        run: echo "$TITLE"
      - run: |
          echo start

          echo "${{ github.event.pull_request.body }}"
      - run: >
          echo ${{ github.event.comment.body }}
      - name: after
        with:
          x: ${{ github.event.issue.body }}
      - run: echo ${{ github.sha }}
"""


def test_an_event_expression_inside_a_run_step_is_flagged():
    found = scan(".github/workflows/triage.yml", WORKFLOW)
    assert [(f["rule"], f["line"]) for f in found] == [
        ("gha-expression-injection", 6), ("gha-expression-injection", 15), ("gha-expression-injection", 17)]
    assert scan("repo/.github/workflows/x.yaml", "      - run: echo ${{ github.event.a }}")
    assert scan(".github/ci.yml", WORKFLOW) == []                       # not a workflow
    assert scan("workflows/triage.yml", WORKFLOW) == []
    assert scan(".github\\workflows\\triage.yml", WORKFLOW)            # a Windows spelling


# ── bounds ───────────────────────────────────────────────────────────────────────

def test_findings_and_the_scanned_bytes_are_bounded(monkeypatch):
    many = "\n".join("eval(x)" for _ in range(50))
    assert len(scan("a.py", many)) == code_guidance.MAX_FINDINGS
    runs = "\n".join(f"- run: echo ${{{{ github.event.a{i} }}}}" for i in range(40))
    assert len(scan(".github/workflows/w.yml", runs)) == code_guidance.MAX_FINDINGS
    monkeypatch.setattr(code_guidance, "MAX_SCAN_BYTES", 20)
    # Cut short, and said so (review-H507 F5): it does not read as a clean file.
    assert scan("a.py", "x = 1\n" * 5 + "eval(x)\n") == [_incomplete(4)]
    assert scan("a.txt", "x = 1\n" * 5 + "eval(x)\n") == []                # never scanned at all


# ── the approval card and the write result ───────────────────────────────────────

def test_labels_never_set_a_class_and_are_bounded():
    labels = code_guidance.labels("a.py", "\n".join(f"eval(x{i})" for i in range(30)))
    assert "class" not in labels
    assert labels["code_warning_count"] == code_guidance.MAX_FINDINGS
    assert len(labels["code_warnings"]) <= 200 and labels["code_warnings"].startswith("py-eval@1, py-eval@2")
    assert labels["notice"] == "code warnings: 20 risky pattern(s)"
    assert code_guidance.labels("a.py", "print('hi')") is None


def test_the_switch_turns_it_off(monkeypatch):
    assert code_guidance.enabled() is True
    settings_db.put_category("security", {"code_guidance": False})
    assert code_guidance.enabled() is False
    assert code_guidance.labels("a.py", "eval(x)") is None
    assert code_guidance.result_fields("a.py", "eval(x)") == {}
    monkeypatch.setattr(settings_db, "get_value", lambda *a, **k: None)
    assert code_guidance.enabled() is True                         # only an explicit off
    monkeypatch.setattr(settings_db, "get_value", lambda *a, **k: 1 / 0)
    assert code_guidance.enabled() is True                         # unreadable: stays on


@pytest.fixture
def wiring(tmp_path):
    from agents.core.file_tools import FileScope, FileTools, SnapshotStore, register_file_tools
    from agents.core.tool_rpc import ToolRPCServer

    root = tmp_path / "workspace"
    root.mkdir()
    cards = []

    def enqueue(actor, kind, title, payload=None, **kwargs):
        cards.append({"title": title, "payload": payload})
        return len(cards)

    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"), max_bytes=65536)
    server = ToolRPCServer(enqueue=enqueue, execution_context_check=lambda context, task: True)
    register_file_tools(server, tools, enabled=True)
    return server, tools, root, cards


class _Task:
    def __init__(self, payload, agent="jarvis"):
        self.payload = payload
        self.agent = agent


CODE = "import pickle, subprocess\nx = pickle.load(f)\nsubprocess.run(c, shell=True)\n"


def test_the_card_carries_the_warnings_and_the_approved_write_runs_and_warns(wiring):
    server, tools, root, cards = wiring
    out = asyncio.run(server.handle({"tool": "file_write", "args": {"path": "job.py", "content": CODE}}))
    assert out["reason"] == "approval_required"
    card = cards[-1]
    assert card["payload"]["code_warnings"] == "py-pickle-load@2, py-shell-true@3"
    assert card["payload"]["code_warning_count"] == 2 and "class" not in card["payload"]
    assert card["title"] == "Tool 'file_write' via RPC — code warnings: 2 risky pattern(s)"
    done = asyncio.run(server.execute(_Task(card["payload"]), execution_context=object()))
    assert (root / "job.py").read_text(encoding="utf-8") == CODE                   # never blocked
    result = done.get("result", done)
    assert [w["rule"] for w in result["code_warnings"]] == ["py-pickle-load", "py-shell-true"]
    assert "not refusals" in result["code_guidance"]


def test_a_clean_write_and_a_non_code_file_are_untouched(wiring):
    server, tools, root, cards = wiring
    asyncio.run(server.handle({"tool": "file_write", "args": {"path": "notes.txt", "content": "eval(x)"}}))
    assert cards[-1]["title"] == "Tool 'file_write' via RPC"
    assert set(cards[-1]["payload"]) == {"tool", "args", "target"}
    result = asyncio.run(tools.write_file({"path": "ok.py", "content": "print(1)\n"}, approved=True))
    assert result["ok"] is True and "code_warnings" not in result


def test_the_instruction_class_and_the_warnings_share_the_card(wiring, monkeypatch):
    from agents.core import file_tools

    server, tools, root, cards = wiring
    monkeypatch.setattr(file_tools, "instruction_labels", lambda *names: {
        "class": file_tools.INSTRUCTION_CLASS, "steers_future_runs": True, "notice": file_tools.INSTRUCTION_NOTICE})
    labels = tools.classify_mutation({"path": "hook.py", "content": "eval(x)\n"})
    assert labels["class"] == file_tools.INSTRUCTION_CLASS and labels["code_warning_count"] == 1
    assert labels["notice"] == f"{file_tools.INSTRUCTION_NOTICE}; code warnings: 1 risky pattern(s)"
    only_class = tools.classify_mutation({"path": "hook.py", "content": "print(1)\n"})
    assert only_class == {"class": file_tools.INSTRUCTION_CLASS, "steers_future_runs": True,
                          "notice": file_tools.INSTRUCTION_NOTICE}
    assert tools.classify_mutation({"path": "hook.py"})["class"] == file_tools.INSTRUCTION_CLASS  # a delete


def test_a_failing_scan_never_fails_the_write(wiring, monkeypatch):
    server, tools, root, cards = wiring
    monkeypatch.setattr(code_guidance, "result_fields", lambda *a: 1 / 0)
    result = asyncio.run(tools.write_file({"path": "a.py", "content": "eval(x)\n"}, approved=True))
    assert result["ok"] is True and "code_warnings" not in result
    assert (root / "a.py").exists()


def test_a_refused_write_carries_no_warnings(wiring):
    server, tools, root, cards = wiring
    result = asyncio.run(tools.write_file({"path": "../outside.py", "content": "eval(x)\n"}, approved=True))
    assert result["ok"] is False and "code_warnings" not in result


# ── skills ───────────────────────────────────────────────────────────────────────

def test_scan_tree_walks_a_skill_folder(tmp_path):
    root = tmp_path / "skill"
    (root / "lib").mkdir(parents=True)
    (root / "SKILL.md").write_text("# S\neval(x) in prose\n", encoding="utf-8")
    (root / "main.py").write_text("import os\nos.system(c)\n", encoding="utf-8")
    (root / "lib" / "ui.js").write_text("el.innerHTML = x\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"\x00\xffeval(x)")
    outside = tmp_path / "outside.py"
    outside.write_text("os.system(c)\n", encoding="utf-8")
    with contextlib.suppress(OSError):                                # no symlinks here: fine
        (root / "link.py").symlink_to(outside)                        # never followed
    found = code_guidance.scan_tree(root)
    assert [(w["path"], w["rule"], w["line"]) for w in found] == [
        ("lib/ui.js", "js-inner-html", 1), ("main.py", "py-os-system", 2)]
    assert code_guidance.scan_tree(tmp_path / "missing") == []
    # Only code files count toward the bound, and the one it stops at is named
    # (review-H507 F5): SKILL.md and blob.bin come first and are never read.
    assert [(w["path"], w["rule"]) for w in code_guidance.scan_tree(root, max_files=1)] == [
        ("lib/ui.js", "js-inner-html"), ("main.py", "scan-incomplete")]
    settings_db.put_category("security", {"code_guidance": False})
    assert code_guidance.scan_tree(root) == []


def test_scan_tree_is_bounded(tmp_path):
    root = tmp_path / "skill"
    root.mkdir()
    for i in range(30):
        (root / f"m{i:02}.py").write_text("eval(x)\n", encoding="utf-8")
    assert len(code_guidance.scan_tree(root)) == code_guidance.MAX_FINDINGS


def test_a_generated_skill_is_scanned(tmp_path, monkeypatch):
    from agents.core.skills import loader as skill_loader
    from agents.core.skills.loader import SkillLoader

    monkeypatch.setattr(skill_loader, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(skill_loader, "_user_skills_dir", lambda: tmp_path / "user-skills")
    loader = SkillLoader()
    name = loader.generate_skill("jarvis", "summarise the weather report", ["read it", "sum it"])
    assert name and loader.last_generation_warnings == []              # the template is clean
    real_scan = code_guidance.scan_tree
    monkeypatch.setattr(code_guidance, "scan_tree", lambda root: [{"path": "main.py", "rule": "py-eval", "line": 1,
                                                                   "message": "m"}] + real_scan(root))
    name = loader.generate_skill("jarvis", "convert the currency amounts", ["a", "b"])
    assert name and [w["rule"] for w in loader.last_generation_warnings] == ["py-eval"]
    monkeypatch.setattr(code_guidance, "scan_tree", lambda root: 1 / 0)
    assert loader.generate_skill("jarvis", "track the parcel deliveries", ["a", "b"])
    assert loader.last_generation_warnings == []


def _package(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def test_an_installed_package_is_scanned_and_the_route_says_so(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.skills.marketplace import SkillMarketplace

    market = SkillMarketplace(skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "m.db"))
    skill_md = "---\nname: risky\ndescription: does risky things\n---\n# Risky\n\nUse it.\n"
    ok = market.install_from_zip(_package({"SKILL.md": skill_md, "main.py": "import os\nos.system(c)\n"}))
    assert ok is True and [w["rule"] for w in market.last_install_warnings] == ["py-os-system"]
    assert market.install_from_zip(_package({"SKILL.md": skill_md, "main.py": "print(1)\n"})) is True
    assert market.last_install_warnings == []

    class _Orch:
        marketplace = market
        skills = type("S", (), {"discover": lambda self: None})()

    monkeypatch.setattr(web, "orch", _Orch())
    monkeypatch.setattr(web, "ADMIN_TOKEN", "h507")
    client = TestClient(web.app)
    import base64

    body = {"zip_base64": base64.b64encode(_package({"SKILL.md": skill_md, "main.py": "eval(x)\n"})).decode()}
    reply = client.post("/api/skills/marketplace/install-zip", json=body, headers={"X-Admin-Token": "h507"}).json()
    assert reply["ok"] is True and [w["rule"] for w in reply["code_warnings"]] == ["py-eval"]
    clean = {"zip_base64": base64.b64encode(_package({"SKILL.md": skill_md, "main.py": "print(2)\n"})).decode()}
    assert client.post("/api/skills/marketplace/install-zip", json=clean,
                       headers={"X-Admin-Token": "h507"}).json() == {"ok": True}
    assert market.install_from_zip(_package({"SKILL.md": skill_md, "main.py": "eval(x)\n"})) is True
    assert market.last_install_warnings                                  # warned
    monkeypatch.setattr(code_guidance, "scan_tree", lambda root: 1 / 0)
    assert market.install_from_zip(_package({"SKILL.md": skill_md, "main.py": "eval(x)\n"})) is True
    assert market.last_install_warnings == []                            # not the last one's


def test_the_setting_row_is_declared():
    rows = {(r["category"], r["key"]): r for r in settings_db.DEFAULTS}
    row = rows[code_guidance.SETTING]
    assert row["kind"] == "toggle" and row["value"] is True


# ── review round (review-H507) ───────────────────────────────────────────────────

# F1 — the scan runs on the hub's event loop (the card is labelled before it exists),
# so no line may cost more than linear time and no file more than a bounded wall time.
@pytest.mark.parametrize("path,text", [
    ("x.html", "<script " * 125_000),
    ("x.py", "yaml.load(" * 100_000 + "Loader=SafeLoader"),
    ("x.py", "torch.load(" * 90_000 + "weights_only=True"),
    ("x.py", "hashlib.md5(" * 80_000),
    ("x.py", "cur.execute(" * 80_000),
    ("x.js", "require('child_process')\n" + "exec(" * 190_000),
    ("x.py", ("yaml.load(" * 50 + "Loader=SafeLoader\n") * 1900),
])
def test_a_crafted_megabyte_scans_in_under_a_second(path, text):
    started = time.monotonic()
    scan(path, text)
    assert time.monotonic() - started < 1.0


def test_a_scan_out_of_time_stops_and_says_where(monkeypatch):
    monkeypatch.setattr(code_guidance, "SCAN_SECONDS", -1.0)
    assert scan("a.py", "x = 1\neval(x)\n") == [_incomplete(1)]
    assert scan(".github/workflows/w.yml", "- run: echo ${{ github.event.a }}\n") == [_incomplete(1)]


def test_the_card_for_a_crafted_megabyte_is_labelled_promptly(tmp_path):
    from agents.core.file_tools import FileScope, FileTools, SnapshotStore, register_file_tools
    from agents.core.tool_rpc import ToolRPCServer

    root = tmp_path / "workspace"
    root.mkdir()
    tools = FileTools(FileScope([root]), snapshots=SnapshotStore(tmp_path / "snaps"), max_bytes=2_000_000)
    server = ToolRPCServer(enqueue=lambda *a, **k: 1, execution_context_check=lambda context, task: True)
    register_file_tools(server, tools, enabled=True)
    started = time.monotonic()
    out = asyncio.run(server.handle({"tool": "file_write", "args": {"path": "x.html", "content": "<script " * 125_000}}))
    assert out["reason"] == "approval_required" and time.monotonic() - started < 3.0


# F2 — a gated write ends the turn, so the answer and the loop's reply carry them.
def test_the_approval_answer_tells_the_model_the_warnings(wiring):
    server, tools, root, cards = wiring
    out = asyncio.run(server.handle({"tool": "file_write", "args": {"path": "job.py", "content": CODE}}))
    assert out["reason"] == "approval_required"
    assert out["code_warnings"] == "py-pickle-load@2, py-shell-true@3" and out["code_warning_count"] == 2
    clean = asyncio.run(server.handle({"tool": "file_write", "args": {"path": "ok.py", "content": "print(1)\n"}}))
    assert clean["reason"] == "approval_required" and "code_warnings" not in clean


def test_the_agent_loop_says_the_warnings_when_it_pauses_for_approval(wiring):
    from agents.core.agent_runtime import _APPROVAL_REPLY, AgentToolRuntime
    from agents.core.llm.tool_protocol import ToolCall, ToolTurn

    server, tools, root, cards = wiring

    class _Backend:
        supports_tools = True
        calls = 0

        async def generate_tool_turn(self, **kwargs):
            self.calls += 1
            args = {"path": "job.py", "content": CODE}
            return ToolTurn(tool_calls=(ToolCall(id="w1", name="file_write", raw_arguments=json.dumps(args),
                                                 arguments=args),), finish_reason="tool_calls")

    backend = _Backend()
    answer = asyncio.run(AgentToolRuntime(server, enabled=lambda: True).run(
        agent_id="jarvis", backend=backend, model="local-model", prompt="write job.py", max_tokens=256))
    assert answer.startswith(_APPROVAL_REPLY) and backend.calls == 1
    assert "py-pickle-load@2, py-shell-true@3" in answer and "not refusals" in answer
    assert not (root / "job.py").exists() and cards[-1]["payload"]["code_warning_count"] == 2


# F3 — a generated skill's warnings reach the caller that answers the model.
def test_a_stale_generation_warning_does_not_survive_an_early_return(tmp_path, monkeypatch):
    from agents.core.skills import loader as skill_loader
    from agents.core.skills.loader import SkillLoader

    monkeypatch.setattr(skill_loader, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(skill_loader, "_user_skills_dir", lambda: tmp_path / "user-skills")
    loader = SkillLoader()
    name = loader.generate_skill("jarvis", "summarise the weather report", ["read it", "sum it"])
    assert name and (tmp_path / "user-skills" / name).is_dir()
    loader.last_generation_warnings = [{"path": "main.py", "rule": "py-eval", "line": 1, "message": "m"}]
    # The generated name includes wall-clock seconds. Force the exact existing
    # directory on the second call so this exercises the early-return branch.
    monkeypatch.setattr(loader, "_name_from_task", lambda _task: name)
    assert loader.generate_skill("jarvis", "summarise the weather report", ["read it", "sum it"]) is None
    assert loader.last_generation_warnings == []


def test_skill_propose_answers_the_generated_skills_warnings():
    from agents.core.skills.tools import TOOL_PROPOSE, register_skill_tools
    from agents.core.tool_rpc import ToolRPCServer

    warned = [{"path": "main.py", "rule": "py-eval", "line": 3, "message": "m"}]

    class _Loader:
        last_generation_problems: list = []
        last_generation_warnings: list = []

        def generate_skill(self, actor, description, steps):
            self.last_generation_warnings = list(warned)
            return "made"

    server = ToolRPCServer()
    register_skill_tools(server, loader=lambda: _Loader(), posture=lambda: "operator/owner", origin=lambda: "hud")
    reply = asyncio.run(server.handle({"tool": TOOL_PROPOSE, "args": {"description": "sum the invoices",
                                                                      "steps": ["open", "sum"]}}))
    assert reply["ok"] is True and reply["result"]["kind"] == "new"
    assert reply["result"]["code_warnings"] == warned
    warned.clear()
    reply = asyncio.run(server.handle({"tool": TOOL_PROPOSE, "args": {"description": "sum the bills",
                                                                      "steps": ["open", "sum"]}}))
    assert reply["ok"] is True and "code_warnings" not in reply["result"]


# F4 — the card scans the file the write lands on, not only the name as spelled.
def test_the_card_scans_the_file_the_write_lands_on(wiring):
    server, tools, root, cards = wiring
    (root / "deploy.py").write_text("", encoding="utf-8")
    try:
        (root / "notes.txt").symlink_to(root / "deploy.py")
    except OSError:
        pytest.skip("no symlinks here")
    labels = tools.classify_mutation({"path": "notes.txt", "content": "import os\nos.system(cmd)\n"})
    assert labels["code_warnings"] == "py-os-system@2"
    flow = "on: issues\njobs:\n  t:\n    steps:\n      - run: echo ${{ github.event.issue.title }}\n"
    for spelled in (".github/./workflows/ci.yml", ".github//workflows/ci.yml"):
        assert tools.classify_mutation({"path": spelled, "content": flow})["code_warnings"] == \
            "gha-expression-injection@5", spelled
    assert tools.classify_mutation({"path": "notes.md", "content": "eval(x)\n"}) is None


# F5 — a package padded with assets is still scanned; a cut scan says it was cut.
def test_a_package_padded_with_assets_is_still_scanned(tmp_path):
    from agents.core.skills.marketplace import SkillMarketplace

    market = SkillMarketplace(skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "m.db"))
    skill_md = "---\nname: padded\ndescription: does risky things\n---\n# Padded\n\nUse it.\n"
    files = {"SKILL.md": skill_md, "main.py": "import os\nos.system(cmd)\n"}
    files.update({f"assets/a{i:03}.png": "x" for i in range(210)})
    assert market.install_from_zip(_package(files)) is True
    assert [(w["path"], w["rule"]) for w in market.last_install_warnings] == [("main.py", "py-os-system")]


def test_a_file_past_the_limit_says_so(monkeypatch):
    monkeypatch.setattr(code_guidance, "SCAN_SECONDS", 60.0)      # the size cut, not a slow runner's clock
    assert scan("a.py", "x = 1\n" * 200_000 + "os.system(c)\n") == [_incomplete(166_667)]


def test_a_tree_cut_short_names_what_it_did_not_read(tmp_path, monkeypatch):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "big.py").write_bytes(b"x = 1\n" * 200_000 + b"os.system(c)\n")     # 1.2 MB
    (root / "main.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.setattr(code_guidance, "SCAN_SECONDS", 60.0)      # the size cut, not a slow runner's clock
    monkeypatch.setattr(code_guidance, "TREE_SECONDS", 60.0)
    found = code_guidance.scan_tree(root)
    assert found == [{"path": "big.py", **_incomplete(166_667)}]              # where the first 1 MB ends
    (root / "late.py").write_text("eval(x)\n", encoding="utf-8")
    monkeypatch.setattr(code_guidance, "TREE_SECONDS", -1.0)
    assert [(w["path"], w["rule"]) for w in code_guidance.scan_tree(root)] == [("big.py", "scan-incomplete")]


# F6 — a `- run: |` block ends at its own step's other keys.
def test_a_dash_run_block_ends_at_its_steps_other_keys():
    flow = """\
on: issues
jobs:
  t:
    steps:
      - run: |
          echo "$TITLE"
        env:
          TITLE: ${{ github.event.issue.title }}
      - run: |
          echo "${{ github.event.issue.body }}"
        with:
          x: ${{ github.event.issue.body }}
        if: ${{ github.event.issue.title != '' }}
"""
    assert [f["line"] for f in scan(".github/workflows/w.yml", flow)] == [10]


# F9 — lines are counted as Python and a shell count them: at a newline only.
def test_line_numbers_follow_newlines_only():
    assert [(f["rule"], f["line"]) for f in scan("a.py", "x = 1\x0cy = 2\neval(z)")] == [("py-eval", 2)]
    assert [(f["rule"], f["line"]) for f in scan("a.py", "s = 'a\u2028b'\neval(z)")] == [("py-eval", 2)]
    assert scan("a.py", "# note\x0ceval(z)\nx = 1\n") == []                # all one comment
    assert [(f["rule"], f["line"]) for f in scan("a.py", 'import os\nos.system\x0c("ls")\n')] == [
        ("py-os-system", 2)]
    assert [f["line"] for f in scan("a.py", "x = 1\r\neval(z)\r\n")] == [2]
    assert [f["line"] for f in scan("a.py", "x = 1\reval(z)\r")] == [2]
    flow = "on: issues\n# a\x0cb\njobs:\n  t:\n    steps:\n      - run: echo ${{ github.event.a }}\n"
    assert [f["line"] for f in scan(".github/workflows/w.yml", flow)] == [6]


# F10 — dotfiles are shell files.
@pytest.mark.parametrize("path", [".env", "app/.env", ".env.local", ".bashrc", ".zshrc", ".profile"])
def test_dotfiles_are_scanned_as_shell(path):
    assert _rules(path, "export NODE_TLS_REJECT_UNAUTHORIZED=0") == ["js-tls-off"]


# F11 — safe mode puts the switch back on.
def test_safe_mode_forces_the_switch_on(monkeypatch):
    from agents.core import safe_mode

    settings_db.put_category("security", {"code_guidance": False})
    assert code_guidance.enabled() is False
    monkeypatch.setenv(safe_mode.ENV_NAME, "1")
    try:
        assert code_guidance.enabled() is True
    finally:
        safe_mode.reset()


# ── the review round's mutation pass: what the bounded guards promise ─────────────

def test_a_nested_call_on_a_later_line_is_read_to_its_own_closing_parenthesis():
    text = "import yaml\n\ncfg = yaml.load(open(a)); other(Loader=yaml.SafeLoader)\n"
    assert [(f["rule"], f["line"]) for f in scan("a.py", text)] == [("py-yaml-load", 3)]


def test_a_guard_reads_at_most_its_bound_of_arguments():
    far = "yaml.load(" + "a" * (code_guidance.MAX_CALL_CHARS + 50) + ", Loader=yaml.SafeLoader)"
    assert _rules("a.py", far) == ["py-yaml-load"]                     # past the bound: not read, so warned
    assert _rules("a.py", "yaml.load(" + "a" * 50 + ", Loader=yaml.SafeLoader)") == []


def test_a_line_of_many_safe_calls_stays_quiet():
    line = "; ".join(["yaml.load(a, Loader=yaml.SafeLoader)"] * (code_guidance.MAX_CALLS_PER_LINE + 1))
    assert _rules("a.py", line) == []                                  # the guard stops reading; no finding


def test_the_card_names_each_finding_once_in_line_order():
    assert code_guidance.labels("a.py", "eval(x)\n", "a.pyw")["code_warnings"] == "py-eval@1"
    both = code_guidance.labels("setup.sh", "eval(x)\nNODE_TLS_REJECT_UNAUTHORIZED=0\n", "setup.py")
    assert both["code_warnings"] == "py-eval@1, js-tls-off@2" and both["code_warning_count"] == 2


def test_the_card_says_when_the_code_was_not_fully_scanned(monkeypatch):
    monkeypatch.setattr(code_guidance, "MAX_SCAN_BYTES", 20)
    cut = code_guidance.labels("a.py", "x = 1\n" * 5)
    assert cut["notice"] == "code not fully scanned" and cut["code_warnings"] == "scan-incomplete@4"
    risky = code_guidance.labels("a.py", "eval(x)\n" + "x = 1\n" * 5)
    assert risky["notice"] == "code warnings: 1 risky pattern(s), not fully scanned"


def test_a_file_scan_keeps_to_the_folders_deadline(tmp_path, monkeypatch):
    import types

    clock = iter(range(10_000))
    monkeypatch.setattr(code_guidance, "time", types.SimpleNamespace(monotonic=lambda: next(clock) * 0.01))
    monkeypatch.setattr(code_guidance, "TREE_SECONDS", 0.05)             # passes a few lines into the file
    monkeypatch.setattr(code_guidance, "SCAN_SECONDS", 100.0)
    root = tmp_path / "skill"
    root.mkdir()
    (root / "main.py").write_text("x = 1\n" * 50 + "eval(x)\n", encoding="utf-8")
    found = code_guidance.scan_tree(root)
    assert [w["rule"] for w in found] == ["scan-incomplete"] and found[0]["line"] < 50


def test_the_pause_reply_names_only_the_queued_writes_warnings():
    from agents.core.agent_runtime import _APPROVAL_REPLY, _approval_reply

    ran = {"ok": True, "tool": "file_write", "code_warnings": "py-eval@1"}          # written, not queued
    queued = {"ok": False, "reason": "approval_required", "tool": "file_write", "code_warnings": "py-os-system@2"}
    assert _approval_reply([ran, {"ok": False, "reason": "approval_required", "tool": "file_write"}]) == _APPROVAL_REPLY
    assert _approval_reply([ran, queued]).endswith("(warnings, not refusals): py-os-system@2.")
