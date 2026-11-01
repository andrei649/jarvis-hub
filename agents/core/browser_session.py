"""Process-local, fresh-profile browser ownership and grounded element references."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

MAX_SESSIONS = 4
MAX_REFS = 100
MAX_FRAMES = 16
MAX_REF_TEXT = 128
MAX_REF_TARGET = 1024
MAX_IMAGE_SCAN = 100
MAX_IMAGES = 24
MAX_IMAGE_SRC = 512
MAX_IMAGE_BYTES = 8_000
# An approved follow-up (act, close) runs only on a later autonomy tick: the loop sleeps
# system.autonomy_tick (60 s by default) before every tick and approval does not wake it.
# A 60 s idle limit therefore expired every session before its next step could run (review
# of #1321); five minutes leaves the owner time to approve within the 10-minute lifetime.
IDLE_SECONDS = 300.0
LIFETIME_SECONDS = 600.0
logger = logging.getLogger('jarvis.browser.session')


class SessionRefused(ValueError):
    """Bounded refusal; never includes page text, profile paths or request URLs."""


_SEMANTICS = """(e) => {
  const tag = e.tagName.toLowerCase();
  const role = e.getAttribute('role') || tag;
  const name = e.getAttribute('aria-label') || e.getAttribute('title') ||
    (tag === 'input' ? (e.getAttribute('placeholder') || '') :
      tag === 'img' ? (e.getAttribute('alt') || '') : (e.textContent || '').trim());
  const form = e.form || (tag === 'form' ? e : null);
  const target = JSON.stringify({
    own: [e.getAttribute('href') || '', e.getAttribute('action') || '',
      e.getAttribute('type') || '', e.getAttribute('form') || '',
      tag === 'img' ? [e.getAttribute('src') || '', e.getAttribute('srcset') || '',
        e.getAttribute('sizes') || '', e.currentSrc || ''] : ''],
    form: form ? [form.action, form.method, form.target, form.enctype, !!form.noValidate] : null,
    override: [e.getAttribute('formaction') || '', e.getAttribute('formmethod') || '',
      e.getAttribute('formtarget') || '', e.getAttribute('formenctype') || '',
      e.hasAttribute('formnovalidate')],
    effective: form && (tag === 'button' || tag === 'input') ?
      [e.formAction || form.action, e.formMethod || form.method,
       e.formTarget || form.target, e.formEnctype || form.enctype, !!e.formNoValidate] : null,
  });
  return {role, name, target, connected: e.isConnected,
    focus: e.ownerDocument.activeElement === e,
    disabled: !!e.disabled, hidden: e.getAttribute('aria-hidden') === 'true'};
}"""

_IMAGE_OBSERVATION = "(e) => { const semantics = (" + _SEMANTICS + """)(e); return {
  connected: e.isConnected, hidden: e.getAttribute('aria-hidden') === 'true',
  alt: (e.getAttribute('alt') || '').slice(0, 129),
  src: (e.currentSrc || e.src || '').slice(0, 513),
  src_truncated: (e.currentSrc || e.src || '').length > 512,
  width: e.naturalWidth || e.width || 0, height: e.naturalHeight || e.height || 0,
  semantics,
}; }"""


@dataclass
class LiveRef:
    handle: object
    frame: object
    frame_url: str
    frame_epoch: int
    role: str
    name: str
    target: str
    visible: bool
    focused: bool


@dataclass
class BrowserSession:
    id: str
    driver: object
    policy: object
    pins: object
    agent: str
    owner: str
    owner_task: object
    head: str
    registration_key: str
    registration_epoch: str | None = None
    created: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    generation: int = 0
    active_task: object | None = None
    active_args: dict | None = None
    active_worker: asyncio.Task | None = None
    # Set when an owner or reaper close cancels active_worker: that one cancellation ends
    # the step, never the executor or autonomy loop that is running the task (#1321).
    close_cancelled: bool = False
    closed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refs: dict[str, LiveRef] = field(default_factory=dict)
    frame_epochs: dict[int, int] = field(default_factory=dict)
    next_ref: int = 1
    # Element refs minted by the latest snapshot(). A new snapshot supersedes them: without
    # this, repeated snapshots of one document kept appending refs for the same elements
    # until MAX_REFS stopped every later snapshot (Codex review, #1321).
    snapshot_refs: set[str] = field(default_factory=set)
    # The same for get_images: each call supersedes the previous call's image refs, or a
    # gallery polled a few times filled MAX_REFS and no later snapshot minted a ref.
    image_refs: set[str] = field(default_factory=set)
    _observed_page: object | None = None

    def current(self) -> bool:
        now = time.monotonic()
        return (not self.closed and (self.active_task is not None or now - self.last_used < IDLE_SECONDS)
                and now - self.created < LIFETIME_SECONDS)

    def idle(self) -> bool:
        return self.active_worker is None and not self.lock.locked()

    def invalidate(self, frame=None) -> None:
        if frame is None:
            self.refs.clear()
        else:
            self.refs = {key: value for key, value in self.refs.items() if value.frame is not frame}
            ident = id(frame)
            self.frame_epochs[ident] = self.frame_epochs.get(ident, 0) + 1
        self.generation += 1

    def observe_page(self, page) -> None:
        if page is self._observed_page:
            return
        self._observed_page = page
        page.on('framenavigated', lambda frame: self.invalidate(frame))
        page.on('framedetached', lambda frame: self.invalidate(frame))

    @staticmethod
    def _bounded(value, limit=MAX_REF_TEXT) -> str | None:
        if not isinstance(value, str) or len(value) > limit:
            return None
        return value

    async def snapshot(self) -> dict:
        """Only actual live handles mint refs; ARIA-only rows remain observations."""
        page = await self.driver._ensure_started()
        self.observe_page(page)
        observation = await self.driver.observe_snapshot()
        for stale in self.snapshot_refs:
            self.refs.pop(stale, None)
        self.snapshot_refs.clear()
        output = []
        skipped = 0
        for frame in list(page.frames)[:MAX_FRAMES]:
            if len(self.refs) >= MAX_REFS or len(output) >= MAX_REFS:
                break
            url = str(frame.url)
            if not url.startswith(('http://', 'https://')):
                continue
            allowed, _ = self.policy.domain_allowed(url)
            if not allowed or urlsplit(url).hostname not in self.pins.pinned_hosts():
                continue
            if frame is not page.main_frame:
                try:
                    owner = await frame.frame_element()
                    if not await owner.is_visible():
                        continue
                except Exception:
                    skipped += 1
                    continue
            try:
                locator = frame.locator('a,button,input,select,textarea,[role],[tabindex]')
                count = min(await locator.count(), MAX_REFS - len(output))
            except Exception:
                skipped += 1
                continue
            for index in range(count):
                try:
                    handle = await locator.nth(index).element_handle()
                    if handle is None:
                        continue
                    if not await handle.is_visible():
                        continue
                    semantics = await handle.evaluate(_SEMANTICS)
                    if (type(semantics) is not dict or not semantics.get('connected')
                            or semantics.get('hidden') or semantics.get('disabled')):
                        continue
                    role = self._bounded(semantics.get('role'))
                    name = self._bounded(semantics.get('name'))
                    target = self._bounded(semantics.get('target'), MAX_REF_TARGET)
                    if role is None or name is None or target is None:
                        continue
                    ref = f'@e{self.next_ref}'
                    self.next_ref += 1
                    self.refs[ref] = LiveRef(handle, frame, url,
                                             self.frame_epochs.get(id(frame), 0), role, name, target,
                                             True, bool(semantics.get('focus')))
                    self.snapshot_refs.add(ref)
                    output.append({'ref': ref, 'role': role, 'name': name,
                                   'focused': bool(semantics.get('focus')),
                                   'frame_origin': urlsplit(url).scheme + '://' + urlsplit(url).netloc})
                    if len(json.dumps(output, ensure_ascii=False).encode()) > 8_000:
                        self.refs.pop(ref)
                        self.snapshot_refs.discard(ref)
                        output.pop()
                        break
                except Exception:
                    skipped += 1
                    continue
        if skipped:
            logger.debug('browser snapshot skipped inspection failures count=%d', skipped)
        observation['refs'] = output
        observation['generation'] = self.generation
        return observation

    async def get_images(self) -> dict:
        """Inventory only visible live nodes; no request, download or new pin."""
        page = await self.driver._ensure_started()
        self.driver._assert_execution_current()
        self.observe_page(page)
        for stale in self.image_refs:
            self.refs.pop(stale, None)
        self.image_refs.clear()
        output: list[dict] = []
        dropped = 0
        truncated = len(page.frames) > MAX_FRAMES
        scanned = 0
        budget_exhausted = False
        skipped_frames = 0
        for frame in list(page.frames)[:MAX_FRAMES]:
            url = str(frame.url)
            parsed_frame = urlsplit(url)
            if (parsed_frame.scheme not in {'http', 'https'} or not parsed_frame.hostname
                    or len(parsed_frame.netloc) > 253
                    or parsed_frame.hostname not in self.pins.pinned_hosts()):
                continue
            allowed, _ = await asyncio.to_thread(self.policy.domain_allowed, url)
            self.driver._assert_execution_current()
            if not allowed:
                continue
            if frame is not page.main_frame:
                try:
                    owner = await frame.frame_element()
                    if not await owner.is_visible():
                        continue
                except Exception:
                    skipped_frames += 1
                    continue
            try:
                locator = frame.locator('img')
                count = await locator.count()
            except Exception:
                truncated = True
                continue
            remaining = max(0, MAX_IMAGE_SCAN - scanned)
            if count > remaining:
                truncated = True
                dropped += count - remaining
            if budget_exhausted or len(output) >= MAX_IMAGES:
                if min(count, remaining):
                    truncated = True
                    dropped += min(count, remaining)
                continue
            for index in range(min(count, remaining)):
                scanned += 1
                if len(output) >= MAX_IMAGES:
                    truncated = True
                    dropped += min(count, remaining) - index
                    break
                try:
                    handle = await locator.nth(index).element_handle()
                    if handle is None or not await handle.is_visible():
                        continue
                    raw = await handle.evaluate(_IMAGE_OBSERVATION)
                    self.driver._assert_execution_current()
                    if type(raw) is not dict or not raw.get('connected') or raw.get('hidden'):
                        continue
                    source = raw.get('src')
                    alt = raw.get('alt')
                    if type(source) is not str or type(alt) is not str:
                        continue
                    source = source if len(source) <= MAX_IMAGE_SRC and not raw.get('src_truncated') else ''
                    alt = alt[:MAX_REF_TEXT]
                    try:
                        parsed = urlsplit(source)
                        clean_http = (parsed.scheme in {'http', 'https'} and parsed.hostname
                                      and parsed.username is None and parsed.password is None
                                      and (parsed.port is None or 1 <= parsed.port <= 65_535)
                                      and not parsed.fragment and not any(ord(char) <= 32 or ord(char) == 127
                                                                          for char in source))
                    except ValueError:
                        clean_http = False
                        parsed = None
                    if not clean_http:
                        source = ''
                    pinned = bool(clean_http and parsed.hostname in self.pins.pinned_hosts())
                    fetchable = False
                    if pinned:
                        fetchable, _ = await asyncio.to_thread(self.policy.domain_allowed, source)
                        self.driver._assert_execution_current()
                    width, height = raw.get('width'), raw.get('height')
                    width = width if type(width) is int and 0 <= width <= 100_000 else 0
                    height = height if type(height) is int and 0 <= height <= 100_000 else 0
                    row = {'source_url': source, 'alt': alt, 'width': width,
                           'height': height, 'fetchable': fetchable,
                           'frame_origin': f'{parsed_frame.scheme}://{parsed_frame.netloc}',
                           'document_epoch': self.frame_epochs.get(id(frame), 0)}
                    semantics = raw.get('semantics')
                    if (type(semantics) is dict and semantics.get('connected')
                            and not semantics.get('hidden') and not semantics.get('disabled')
                            and len(self.refs) < MAX_REFS):
                        role = self._bounded(semantics.get('role'))
                        name = self._bounded(semantics.get('name'))
                        target = self._bounded(semantics.get('target'), MAX_REF_TARGET)
                        if role == 'img' and name is not None and target is not None:
                            ref = f'@e{self.next_ref}'
                            row['ref'] = ref
                            self.refs[ref] = LiveRef(handle, frame, url,
                                                     self.frame_epochs.get(id(frame), 0),
                                                     role, name, target, True, False)
                            self.image_refs.add(ref)
                            self.next_ref += 1
                    if len(json.dumps([*output, row], ensure_ascii=False).encode()) > MAX_IMAGE_BYTES:
                        if 'ref' in row:
                            self.refs.pop(row['ref'], None)
                            self.image_refs.discard(row['ref'])
                        truncated = True
                        dropped += min(count, remaining) - index
                        budget_exhausted = True
                        break
                    output.append(row)
                except Exception:
                    dropped += 1
                    truncated = True
        if skipped_frames:
            logger.debug('browser image frames skipped after inspection failure count=%d',
                         skipped_frames)
        return {'observation': 'images', 'images': output, 'count': len(output),
                'dropped': dropped, 'truncated': truncated, 'untrusted': True,
                'generation': self.generation}

    async def resolve_ref(self, ref: str, action: str):
        entry = self.refs.get(ref)
        if not self.current() or entry is None:
            raise SessionRefused('stale_browser_ref')
        page = await self.driver._ensure_started()
        self.driver._assert_execution_current()
        if (entry.frame not in page.frames or entry.frame_epoch != self.frame_epochs.get(id(entry.frame), 0)
                or str(entry.frame.url) != entry.frame_url):
            raise SessionRefused('stale_browser_ref')
        allowed, _ = self.policy.domain_allowed(entry.frame_url)
        if not allowed or urlsplit(entry.frame_url).hostname not in self.pins.pinned_hosts():
            raise SessionRefused('stale_browser_ref')
        try:
            if entry.frame is not page.main_frame:
                owner = await entry.frame.frame_element()
                if not await owner.is_visible():
                    raise SessionRefused('stale_browser_ref')
            if not await entry.handle.is_visible():
                raise SessionRefused('stale_browser_ref')
            semantics = await entry.handle.evaluate(_SEMANTICS)
        except SessionRefused:
            raise
        except Exception:
            raise SessionRefused('stale_browser_ref') from None
        if (type(semantics) is not dict or not semantics.get('connected')
                or semantics.get('hidden') or semantics.get('disabled')
                or (semantics.get('role'), semantics.get('name'), semantics.get('target'))
                    != (entry.role, entry.name, entry.target)
                or (action == 'press' and not semantics.get('focus'))):
            raise SessionRefused('stale_browser_ref')
        self.driver._assert_execution_current()
        return entry.handle


class BrowserOwnershipJournal:
    """Atomic private evidence for only the fresh profiles launched by this runtime."""

    def __init__(self, root: Path):
        self.root = root

    def _safe_root(self, *, create=False) -> None:
        if create:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise SessionRefused('browser_journal_unavailable')

    def _file(self, sid: str) -> Path:
        if re.fullmatch('[0-9a-f]{32}', sid) is None:
            raise SessionRefused('browser_journal_unavailable')
        return self.root / (sid + '.json')

    def entries(self) -> list[Path]:
        if not self.root.exists():
            return []
        self._safe_root()
        return list(self.root.iterdir())

    def write(self, sid: str, record: dict) -> None:
        self._safe_root(create=True)
        path = self._file(sid)
        temporary = self.root / ('.' + sid + '.' + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, path: Path) -> dict:
        self._safe_root()
        if path.parent != self.root or not re.fullmatch('[0-9a-f]{32}\\.json', path.name):
            raise SessionRefused('browser_journal_unavailable')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_nlink != 1:
                raise SessionRefused('browser_journal_unavailable')
            data = stream.read(4097)
            if len(data) > 4096:
                raise SessionRefused('browser_journal_unavailable')
            return json.loads(data)

    def remove(self, sid: str) -> None:
        self._file(sid).unlink(missing_ok=True)

    @staticmethod
    def profile_owned(raw: str) -> Path | None:
        from .browser_playwright import PROFILE_PREFIX

        path = Path(raw)
        root = Path(tempfile.gettempdir()).resolve()
        if (path.parent.resolve() != root or not path.name.startswith(PROFILE_PREFIX)
                or path.is_symlink()):
            return None
        return path

    @staticmethod
    def _refuse_reap(path: Path, reason: str) -> bool:
        """Every refusal says why: a silent False left a CI-only failure undiagnosable."""
        logger.warning('browser orphan reap of %s refused: %s', path.name, reason)
        return False

    async def reap_entry(self, path: Path) -> bool:
        """Only verified native PID/start/profile tuples may be terminated."""
        try:
            record = self.read(path)
            profile = self.profile_owned(record['profile'])
            if profile is None:
                return self._refuse_reap(path, 'profile not owned')
            native = record['native']
            # None: the owner died between the 'profile' and 'native' journal writes, while
            # Chrome was launching. Nothing native was recorded to verify; the profile sweep
            # below still finds whatever names this profile (review of #1321).
            if native is not None and not (type(native) is list and len(native) == 2
                                           and type(native[0]) is int
                                           and type(native[1]) in {int, float}):
                return self._refuse_reap(path, 'native identity malformed')
            import psutil
            marker = '--user-data-dir=' + str(profile)
            controller = record.get('controller')
            owner_process = record.get('owner_process')
            if not (type(owner_process) is list and len(owner_process) == 2
                    and type(owner_process[0]) is int
                    and type(owner_process[1]) in {int, float}):
                return self._refuse_reap(path, 'owner identity malformed')
            if not (type(controller) is list and len(controller) == 2
                    and type(controller[0]) is int and type(controller[1]) in {int, float}):
                return self._refuse_reap(path, 'controller identity malformed')
            try:
                owner = psutil.Process(owner_process[0])
                if owner.create_time() == owner_process[1] and owner.is_running():
                    return self._refuse_reap(path, 'owner still running')
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                return self._refuse_reap(path, 'owner probe failed')
            launch = None
            try:
                launch = psutil.Process(controller[0])
                if launch.create_time() != controller[1] or not launch.is_running():
                    launch = None
                elif not any('playwright/driver' in arg for arg in launch.cmdline()):
                    return self._refuse_reap(path, 'controller is not a playwright driver')
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                return self._refuse_reap(path, 'controller probe failed')
            process = None
            if native is not None:
                pid, started = native
                try:
                    candidate = psutil.Process(pid)
                    # Another start time proves the recorded Chrome is gone and its PID was
                    # reused, as for the controller above: that process is never touched, and
                    # only the sweep of this exact profile below may terminate anything.
                    # Refusing here locked the browser out for as long as the PID's new
                    # holder lived (review of #1321).
                    if candidate.create_time() == started:
                        process = candidate
                except psutil.NoSuchProcess:
                    pass
            if process is not None:
                try:
                    if marker not in process.cmdline():
                        return self._refuse_reap(path, 'native identity changed (marker not in argv)')
                    if not ('chrome' in Path(process.exe()).name.lower()
                            or 'chromium' in Path(process.exe()).name.lower()):
                        return self._refuse_reap(path, f'native is not chrome ({process.exe()})')
                    owned = [process, *process.children(recursive=True)]
                    for item in reversed(owned):
                        item.terminate()
                    _gone, alive = await asyncio.to_thread(psutil.wait_procs, owned, timeout=3)
                    for item in alive:
                        item.kill()
                    _gone, alive = await asyncio.to_thread(psutil.wait_procs, alive, timeout=2)
                    if alive:
                        return self._refuse_reap(path, 'native tree survived kill')
                except psutil.NoSuchProcess:
                    pass
            if launch is not None:
                with contextlib.suppress(psutil.NoSuchProcess):
                    launch.terminate()
                    await asyncio.to_thread(launch.wait, timeout=2)
            # Chrome double-forks helpers (chrome_crashpad_handler) outside the native
            # process tree; they survive the tree's termination and keep writing under
            # the profile (--database=<profile>/Crashpad), so the profile could not be
            # removed and the reap failed on a CI runner's Google Chrome. Only processes
            # naming this exact owned profile are swept, never any other Chrome.
            prefix = str(profile) + os.sep

            def _references(cmdline) -> bool:
                return any(arg == marker or prefix in arg for arg in cmdline or [])

            for _round in range(3):  # the last round must find none
                stragglers = []
                for item in psutil.process_iter(['pid', 'cmdline']):
                    try:
                        if item.pid != os.getpid() and _references(item.info.get('cmdline')):
                            stragglers.append(item)
                    except psutil.NoSuchProcess:
                        continue
                    except psutil.Error:
                        return self._refuse_reap(path, 'process scan failed')
                if not stragglers:
                    break
                for item in stragglers:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        item.terminate()
                _gone, alive = await asyncio.to_thread(psutil.wait_procs, stragglers, timeout=3)
                for item in alive:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        item.kill()
                await asyncio.to_thread(psutil.wait_procs, alive, timeout=2)
            else:
                return self._refuse_reap(path, 'profile-referencing process survived')
            for attempt in range(3):
                if not profile.exists():
                    break
                try:
                    await asyncio.to_thread(shutil.rmtree, profile)
                except OSError:
                    if attempt == 2:
                        return self._refuse_reap(path, 'profile removal failed')
                    await asyncio.sleep(0.2)
            self.remove(path.stem)
            return True
        except Exception:
            logger.warning('browser orphan reap of %s refused: unexpected error', path.name,
                           exc_info=True)
            return False
