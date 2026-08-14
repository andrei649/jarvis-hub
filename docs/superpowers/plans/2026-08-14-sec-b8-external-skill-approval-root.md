# SEC-B8 External Skill Approval Root Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make external-skill in-process execution depend on a keyed signature or an owner approval record outside candidate-controlled skill bytes.

**Architecture:** Add a small atomic `SkillApprovalStore` under the private runtime data root, bind records to canonical path plus stable source fingerprint, and inject it into `SkillLoader`. The loader ignores legacy in-tree markers as authority and fails closed on absent, copied, stale, or corrupt records.

**Tech Stack:** Python 3.12, stdlib hashing/path/time, existing `JsonStore`, pytest, Ruff.

## Global Constraints

- Local-first; no cloud, dependency, route, or credential additions.
- Bundled-skill behavior remains unchanged.
- Keyed HMAC signatures remain sufficient; unkeyed SHA-256 never authenticates.
- Approval persistence lives at `data_path("security", "skill_approvals.json")`.
- `BACKLOG.md` and generated truth remain untouched while draft #876 owns them.

---

### Task 1: Stable source fingerprint and private approval store

**Files:**
- Modify: `agents/core/skills/signing.py`
- Create: `agents/core/skills/approval.py`
- Test: `tests/test_skill_approval_store.py`

**Interfaces:**
- Produces: `source_fingerprint(skill_dir: Path) -> str`
- Produces: `SkillApprovalStore.approve(path: Path) -> dict[str, str]`
- Produces: `SkillApprovalStore.is_approved(path: Path) -> bool`

- [x] **Step 1: Write failing store tests**

```python
def test_approval_is_bound_to_canonical_path_and_source(tmp_path):
    skill = _make_skill(tmp_path / "skills" / "demo")
    store = SkillApprovalStore(tmp_path / "private" / "approvals.json")
    store.approve(skill)
    assert store.is_approved(skill)
    copied = _make_skill(tmp_path / "other" / "demo")
    assert not store.is_approved(copied)
    (skill / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert not store.is_approved(skill)
```

- [x] **Step 2: Verify red**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_approval_store.py -q`

Expected: collection fails because `agents.core.skills.approval` does not exist.

- [x] **Step 3: Implement the stable fingerprint and store**

```python
def source_fingerprint(skill_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in _SIGNED_FILES:
        path = Path(skill_dir) / name
        if path.exists():
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"

class SkillApprovalStore(JsonStore):
    def approve(self, path: Path) -> dict[str, str]:
        canonical = str(path.resolve())
        record = {
            "canonical_path": canonical,
            "source_fingerprint": source_fingerprint(path),
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._records[self._key(canonical)] = record
            self._save()
        return record

    def is_approved(self, path: Path) -> bool:
        canonical = str(path.resolve())
        with self._lock:
            record = self._records.get(self._key(canonical))
        return bool(
            record
            and record.get("canonical_path") == canonical
            and record.get("source_fingerprint") == source_fingerprint(path)
        )
```

- [x] **Step 4: Verify green and adjacent signing tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_approval_store.py tests/test_skill_signing.py -q`

Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add -- agents/core/skills/signing.py agents/core/skills/approval.py tests/test_skill_approval_store.py
git commit -m "feat(security): add external skill approval store"
```

### Task 2: Fail-closed loader trust decision

**Files:**
- Modify: `agents/core/skills/loader.py`
- Modify: `tests/test_skill_signing.py`

**Interfaces:**
- Consumes: `SkillApprovalStore.is_approved(path)`
- Produces: `SkillLoader(approval_store: SkillApprovalStore | None = None)`

- [x] **Step 1: Add hostile failing tests**

```python
def test_forged_external_marker_and_unkeyed_signature_do_not_execute(...):
    signing.sign_skill(skill_dir)
    (skill_dir / "OWNER_APPROVED_IN_PROCESS").write_text("forged\n")
    skill = SkillLoader(approval_store=store).discover()["Personal"]
    assert skill.module is None
    assert skill.sandboxed is True

def test_imported_sidecar_cannot_self_approve(...):
    (skill_dir / "manifest.json").write_text('{"imported": true}')
    signing.sign_skill(skill_dir)
    (skill_dir / "OWNER_APPROVED_IN_PROCESS").write_text("forged\n")
    skill = SkillLoader(approval_store=store).discover()["Imported"]
    assert skill.module is None
```

- [x] **Step 2: Verify red**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_signing.py -k "forged or self_approve" -q`

Expected: both hostile skills execute under the current marker gate.

- [x] **Step 3: Inject the store and replace marker authority**

```python
def _external_skill_may_import(
    path: Path,
    signature_reason: str,
    approval_store: SkillApprovalStore,
) -> bool:
    if not _is_external_skill(path):
        return True
    return signature_reason == "signed" or approval_store.is_approved(path)

class SkillLoader:
    def __init__(self, approval_store: SkillApprovalStore | None = None):
        self.skills = {}
        self._usage = None
        self._approval_store = approval_store or SkillApprovalStore()
```

- [x] **Step 4: Verify green plus bundled/keyed controls**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_signing.py -q`

Expected: hostile marker tests pass; keyed external and bundled controls remain green.

- [x] **Step 5: Commit**

```powershell
git add -- agents/core/skills/loader.py tests/test_skill_signing.py
git commit -m "fix(security): remove in-tree skill approval authority"
```

### Task 3: Explicit owner approval and stale-source invalidation

**Files:**
- Modify: `agents/core/skills/loader.py`
- Modify: `tests/test_cdx8_skill_quarantine.py`
- Modify: `tests/test_generated_skill_contract.py`

**Interfaces:**
- Consumes: `SkillApprovalStore.approve(path)`
- Preserves: `SkillLoader.approve_generated_skill(name) -> bool`

- [x] **Step 1: Write persistence, restart, and mutation tests**

```python
def test_approve_activates_and_persists_outside_skill_tree(loader, store, tmp_path):
    name = _gen(loader)
    assert loader.approve_generated_skill(name)
    assert not (tmp_path / name / "OWNER_APPROVED_IN_PROCESS").exists()
    restarted = SkillLoader(approval_store=store)
    assert restarted.discover()[name.title()].module is not None

def test_approved_skill_change_returns_to_quarantine(loader, store, tmp_path):
    name = _gen(loader)
    assert loader.approve_generated_skill(name)
    (tmp_path / name / "main.py").write_text("VALUE = 2\n")
    skill = SkillLoader(approval_store=store).discover()[name.title()]
    assert skill.module is None and skill.sandboxed is True
```

- [x] **Step 2: Verify red**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cdx8_skill_quarantine.py tests/test_generated_skill_contract.py -q`

Expected: restart cannot use the external registry because approval is still stored in-tree.

- [x] **Step 3: Record approval before activation and clean legacy markers**

```python
self._approval_store.approve(skill_dir)
legacy_marker = skill_dir / LEGACY_OWNER_APPROVED_MARKER
legacy_marker.unlink(missing_ok=True)
(skill_dir / "PENDING_REVIEW").unlink()
self._load_skill(skill_dir)
```

- [x] **Step 4: Verify green**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cdx8_skill_quarantine.py tests/test_generated_skill_contract.py -q`

Expected: explicit approval persists; source changes fail closed.

- [x] **Step 5: Commit**

```powershell
git add -- agents/core/skills/loader.py tests/test_cdx8_skill_quarantine.py tests/test_generated_skill_contract.py
git commit -m "fix(security): bind owner skill approval to source"
```

### Task 4: Full gate, evidence, and draft delivery

**Files:**
- Modify: `docs/MAX_RUNS.md`
- Modify: `docs/test-manual/15-audit-gap-verification.md`
- Do not modify: `BACKLOG.md`, `project-status.json`, or #876-owned roadmap files

**Interfaces:**
- Produces: exact-head verification receipt and next Max pointer

- [ ] **Step 1: Run the full bounded verification sweep**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_approval_store.py tests/test_skill_signing.py tests/test_cdx8_skill_quarantine.py tests/test_generated_skill_contract.py tests/test_marketplace.py -q`

Run: `.venv/Scripts/python.exe -m ruff check agents/core/skills tests/test_skill_approval_store.py tests/test_skill_signing.py tests/test_cdx8_skill_quarantine.py tests/test_generated_skill_contract.py`

Run: `.venv/Scripts/python.exe scripts/check_ai_workflow_policy.py`

Run: `.venv/Scripts/python.exe scripts/status_preflight.py --base origin/main --json`

Run: `git diff --check`

Expected: zero failures; status preflight `in_sync`.

- [ ] **Step 2: Update evidence and Max ledger**

Record SEC-B8/#905 as candidate-fixed without claiming release readiness, list the
exact hostile cases and verification counts, and point the next run to the highest
unowned PARTIAL that does not overlap #876 or #909.

- [ ] **Step 3: Commit only the evidence paths**

```powershell
git add -- docs/MAX_RUNS.md docs/test-manual/15-audit-gap-verification.md
git commit -m "docs(max): record quiet-gale trust-root evidence"
```

- [ ] **Step 4: Re-run the exact final gate, push, and create one draft PR**

Use branch `max/quiet-gale`, base `main`, and an inline design receipt with risk,
rollback, desirability, exact commands/results, and explicit independent-review hold.
