"""Process-local, fresh-profile browser ownership and grounded element references."""
from __future__ import annotations

import asyncio
import contextlib
import json
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
IDLE_SECONDS = 60.0
LIFETIME_SECONDS = 600.0


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
    closed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refs: dict[str, LiveRef] = field(default_factory=dict)
    frame_epochs: dict[int, int] = field(default_factory=dict)
    next_ref: int = 1
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
        output = []
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
                    continue
            try:
                locator = frame.locator('a,button,input,select,textarea,[role],[tabindex]')
                count = min(await locator.count(), MAX_REFS - len(output))
            except Exception:
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
                    output.append({'ref': ref, 'role': role, 'name': name,
                                   'focused': bool(semantics.get('focus')),
                                   'frame_origin': urlsplit(url).scheme + '://' + urlsplit(url).netloc})
                    if len(json.dumps(output, ensure_ascii=False).encode()) > 8_000:
                        self.refs.pop(ref)
                        output.pop()
                        break
                except Exception:
                    continue
        observation['refs'] = output
        observation['generation'] = self.generation
        return observation

    async def get_images(self) -> dict:
        """Inventory only visible live nodes; no request, download or new pin."""
        page = await self.driver._ensure_started()
        self.driver._assert_execution_current()
        self.observe_page(page)
        output: list[dict] = []
        dropped = 0
        truncated = len(page.frames) > MAX_FRAMES
        scanned = 0
        budget_exhausted = False
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
                            self.next_ref += 1
                    if len(json.dumps([*output, row], ensure_ascii=False).encode()) > MAX_IMAGE_BYTES:
                        if 'ref' in row:
                            self.refs.pop(row['ref'], None)
                        truncated = True
                        dropped += min(count, remaining) - index
                        budget_exhausted = True
                        break
                    output.append(row)
                except Exception:
                    dropped += 1
                    truncated = True
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

    async def reap_entry(self, path: Path) -> bool:
        """Only verified native PID/start/profile tuples may be terminated."""
        try:
            record = self.read(path)
            profile = self.profile_owned(record['profile'])
            if profile is None:
                return False
            native = record['native']
            if not (type(native) is list and len(native) == 2
                    and type(native[0]) is int and type(native[1]) in {int, float}):
                return False
            import psutil
            pid, started = native
            marker = '--user-data-dir=' + str(profile)
            controller = record.get('controller')
            owner_process = record.get('owner_process')
            if not (type(owner_process) is list and len(owner_process) == 2
                    and type(owner_process[0]) is int
                    and type(owner_process[1]) in {int, float}):
                return False
            if not (type(controller) is list and len(controller) == 2
                    and type(controller[0]) is int and type(controller[1]) in {int, float}):
                return False
            try:
                owner = psutil.Process(owner_process[0])
                if owner.create_time() == owner_process[1] and owner.is_running():
                    return False
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                return False
            launch = None
            try:
                launch = psutil.Process(controller[0])
                if launch.create_time() != controller[1] or not launch.is_running():
                    launch = None
                elif not any('playwright/driver' in arg for arg in launch.cmdline()):
                    return False
            except psutil.NoSuchProcess:
                pass
            except psutil.Error:
                return False
            try:
                process = psutil.Process(pid)
                if process.create_time() != started or marker not in process.cmdline():
                    return False
                if not ('chrome' in Path(process.exe()).name.lower()
                        or 'chromium' in Path(process.exe()).name.lower()):
                    return False
                owned = [process, *process.children(recursive=True)]
                for item in reversed(owned):
                    item.terminate()
                _gone, alive = await asyncio.to_thread(psutil.wait_procs, owned, timeout=3)
                for item in alive:
                    item.kill()
                _gone, alive = await asyncio.to_thread(psutil.wait_procs, alive, timeout=2)
                if alive:
                    return False
            except psutil.NoSuchProcess:
                pass
            if launch is not None:
                with contextlib.suppress(psutil.NoSuchProcess):
                    launch.terminate()
                    await asyncio.to_thread(launch.wait, timeout=2)
            remaining = []
            for item in psutil.process_iter(['pid', 'cmdline']):
                try:
                    if marker in (item.info.get('cmdline') or []):
                        remaining.append(item.pid)
                except psutil.NoSuchProcess:
                    continue
                except psutil.Error:
                    return False
            if remaining:
                return False
            if profile.exists():
                await asyncio.to_thread(shutil.rmtree, profile)
            self.remove(path.stem)
            return True
        except Exception:
            return False
