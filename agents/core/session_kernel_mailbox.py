"""Host-side session RPC I/O pinned to an opened directory, never worker links."""
from __future__ import annotations

import contextlib
import itertools
import json
import os
import re
import secrets
import stat

from .environments.file_rpc import MAX_RPC_FILE_BYTES, FileRPCRequest, format_sequence


class SessionRPCStore:
    def __init__(self, root, *, max_tool_calls=50):
        self.root = root
        if os.name == "nt":
            from .code_context import _windows_project_handle

            self.fd, self._root_name, self._close_handle = _windows_project_handle(
                root, directory=True, shared_writes=True)
        else:
            self.fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.max_tool_calls = max_tool_calls

    def close(self):
        if os.name == "nt":
            self._close_handle(self.fd)
        else:
            os.close(self.fd)

    def pending_requests(self, limit=64):
        requests = []
        with os.scandir(self.root if os.name == "nt" else self.fd) as entries:
            names = [entry.name for entry in itertools.islice(entries, limit)]
        for name in sorted(names):
            match = re.fullmatch(r'req_(\d{6,10})\.json', name)
            if match is None:
                continue
            seq = int(match[1])
            if seq < 1 or name != f'req_{format_sequence(seq)}.json':
                continue
            try:
                if os.name == "nt":
                    import msvcrt

                    from .code_context import _windows_project_handle

                    handle, final, close = _windows_project_handle(
                        os.path.join(self.root, name))
                    if os.path.commonpath((self._root_name, final)) != self._root_name:
                        close(handle)
                        continue
                    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                else:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=self.fd)
                with os.fdopen(fd, 'rb') as handle:
                    info = os.fstat(handle.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RPC_FILE_BYTES:
                        continue
                    raw = handle.read(MAX_RPC_FILE_BYTES + 1)
                    if len(raw) > MAX_RPC_FILE_BYTES:
                        continue
                payload = json.loads(raw)
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            tool, args = payload.get('tool'), payload.get('args')
            if isinstance(tool, str) and tool and isinstance(args, dict):
                requests.append(FileRPCRequest(seq, tool, args))
        return requests

    def write_response(self, seq, response):
        data = json.dumps(response, ensure_ascii=False).encode('utf-8')
        if len(data) > MAX_RPC_FILE_BYTES:
            data = b'{"ok": false, "reason": "tool_response_too_large"}'
        name = f'res_{format_sequence(seq)}.json'
        tmp = f'.response-{secrets.token_hex(16)}'
        if os.name == "nt":
            fd = os.open(os.path.join(self.root, tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                         0o600)
        else:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
            if os.name == "nt":
                os.replace(os.path.join(self.root, tmp), os.path.join(self.root, name))
            else:
                os.replace(tmp, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        finally:
            with contextlib.suppress(OSError):
                if os.name == "nt":
                    os.unlink(os.path.join(self.root, tmp))
                else:
                    os.unlink(tmp, dir_fd=self.fd)

    def consume(self, seq):
        with contextlib.suppress(OSError):
            name = f'req_{format_sequence(seq)}.json'
            if os.name == "nt":
                os.unlink(os.path.join(self.root, name))
            else:
                os.unlink(name, dir_fd=self.fd)
