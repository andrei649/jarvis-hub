# H011 Windows Native Read Primitives Implementation Plan

> **For agentic workers:** Execute this plan in this task without delegation. Use test-driven development for each source unit.

**Goal:** Add isolated native Windows read-side handle, identity, reparse, bounded-read and private-ACL primitives, plus a focused PR Windows probe, while H011 history remains disabled on Windows.

**Architecture:** `checkpoint_windows_fs.py` owns a lazy ctypes Win32/NT layer and a small fail-closed read facade with RAII handles. The facade opens a local NTFS volume GUID root, descends one component at a time relative to held directory handles, and validates full file IDs and private descriptors. No history, FileTools, SQLite or effect method imports it yet.

**Tech Stack:** Python 3.12 stdlib (`ctypes`, `pathlib`, `dataclasses`), Microsoft `kernel32`, `ntdll`, `advapi32`; pytest; GitHub Actions Windows runner.

**Spec:** [H011 Windows read primitives](../specs/2026-10-29-h011-windows-read-primitives.md). The broader integration is tracked in [the local completion plan](2026-10-28-local-completion.md).

## Global constraints

- Preserve `HISTORY_SUPPORTED = False` on Windows; no effect, store, schema, lock or SQLite adapter in this unit.
- Only a canonical drive-absolute path on a local NTFS volume with persistent ACL capability can open. UNC/device/relative/alias paths and unknown capability refuse.
- The Win32 volume GUID path is obtained by `GetVolumeNameForVolumeMountPointW`; `CreateFileW` opens its trailing-slash root directory, as documented by [Microsoft](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-volume). Re-open and compare the drive mapping and full root ID before reporting a trusted root.
- All path descendants use [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile) with [OBJECT_ATTRIBUTES.RootDirectory and OBJ_DONT_REPARSE](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes) and exactly one validated name. Directory opens omit `FILE_OPEN_REPARSE_POINT`, which is absent from the documented `FILE_DIRECTORY_FILE` compatibility list. Reject reparse attributes/tags and wrong-volume descendants. An unsupported API combination refuses, never falls back to path opens.
- Full identity is [FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info) volume serial (8 bytes) and `FILE_ID_128` (16 bytes). A read compares full stamp before/after and exact size within cap.
- Private ACL verification uses handle-based [GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo) and checks current owner SID, protected non-inherited DACL and a narrow allowlist of owner/SYSTEM/Administrators ACEs; absence or an unrecognized ACE refuses. No ACL modification in this unit.
- Native proof requires actual Windows synthetic NTFS tests. macOS fake tests verify only facade control flow. No service/user data, paid provider, push or full suite.

## Review focus

- A drive letter remapped after bootstrap must make `verify_mount` refuse; test with an injected mapping change.
- A reparse point or mount-point child must refuse before content read; test native junction/symlink and fake tag failures.
- A child whose full 128-bit ID differs only in high bytes must fail `verify_name`; test an injected collision.
- An inherited/Everyone ACL must fail even if the owner SID is correct; test native hostile ACL and fake descriptor.
- An object replaced or grown during a bounded read must fail and close all opened handles; test injected change and native concurrent change.

---

### Task 1: Facade contract and lexical/root fences

**Files:** Create `tests/test_h011_windows_native_fs.py`; create `agents/core/checkpoint_windows_fs.py`.

**Interfaces:** `WindowsHistoryFs(api=None)`, `open_root(path: str) -> HeldHandle`, `verify_mount(root: HeldHandle) -> None`, `open_child(parent: HeldHandle, name: str, *, directory: bool) -> HeldHandle | None`, `verify_name(parent, name, held) -> WinStamp`, `read_exact_bounded(file, cap) -> bytes`, `verify_private_acl(handle) -> None`; `WinFileId`, `WinStamp`, `WindowsFsRefusal(reason)`.

- [ ] Write a fake API test for canonical drive-absolute path, GUID root acquisition, one-component calls, drive remap, invalid names and missing versus denied.
- [ ] Run `pytest tests/test_h011_windows_native_fs.py -k fake -q` and observe RED from the missing module/behavior.
- [ ] Implement only facade validation and RAII handle ownership; run the same test GREEN.

### Task 2: Native read adapter and private descriptor verification

**Files:** Modify `agents/core/checkpoint_windows_fs.py`; extend `tests/test_h011_windows_native_fs.py`.

**Interfaces:** `_Win32Api` is instantiated only on Windows and implements `volume_guid`, `open_volume_root`, `volume_info`, `open_child`, `stamp`, `read`, `acl_info`, `current_user_sid`, `close` for the facade.

- [ ] Write Windows-only synthetic tests for a positive NTFS root/child read, reparse/junction rejection, full ID/name swap, bounds, private and inherited ACLs, unsupported volume, and handle cleanup. Tests must skip on Mac and be enforced as zero skips in Windows CI.
- [ ] Run the file on Mac and observe fake-test RED; native tests remain unproved until Windows runner.
- [ ] Implement explicit ctypes structures, prototypes and NTSTATUS/Win32 error translation. `NtCreateFile` opens one component beneath a held parent; `GetFileInformationByHandleEx` provides FileIdInfo, BasicInfo, StandardInfo and AttributeTagInfo. ACL information is handle-based. Fail closed on any unknown flag/API result.
- [ ] Run fake tests GREEN and keep native assertions for the Windows runner.

### Task 3: Focused premerge native probe

**Files:** Create `.github/workflows/h011-windows-native.yml`.

- [ ] Add a pull-request and manual-dispatch Windows job with `contents: read`, pinned checkout/setup-python actions, Python 3.12, hash-pinned requirements, Ruff on the new module/tests, and the new test file with JUnit XML.
- [ ] The job asserts the JUnit suite has zero skips/errors/failures and prints OS build, filesystem/volume flags and Python version from the native test. Give the job a bounded timeout and preserve the existing `ci.yml` policy unchanged.
- [ ] Run local YAML parse, Ruff, fake tests, adjacent H011 smoke, `git diff --check`; commit source/tests/workflow/plan. Report exact local evidence and that native acceptance awaits root publication and the Windows runner.

## Self-review

Task 1 covers lexical and fake control flow; Task 2 covers all read-side native primitives and five review-focus cases; Task 3 makes native proof a PR checkpoint. All four broader Task45 proof questions remain open for later units. This plan intentionally has no write/delete/publish/GC/SQLite/history wiring.
