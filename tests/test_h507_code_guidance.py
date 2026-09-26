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
import sys
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
    assert scan("a.py", "x = 1\n" * 5 + "eval(x)\n") == []


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
    assert code_guidance.scan_tree(root, max_files=1) == []                   # SKILL.md is first
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
