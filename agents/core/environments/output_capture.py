"""Constant-memory trusted stdout metadata, before display truncation/redaction."""
import codecs
import hashlib


class OutputCapture:
    def __init__(self):
        self._hash = hashlib.sha256()
        self._decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self._count = 0
        self._valid = True

    def feed(self, chunk: bytes) -> None:
        self._hash.update(chunk)
        self._count += len(chunk)
        if self._valid:
            try:
                self._decoder.decode(chunk)
            except UnicodeDecodeError:
                self._valid = False

    def seal(self, snapshot_limit: int, *, successful: bool = True) -> dict:
        if self._valid:
            try:
                self._decoder.decode(b'', final=True)
            except UnicodeDecodeError:
                self._valid = False
        return {'version': 1, 'sha256': self._hash.hexdigest(), 'byte_count': self._count,
                'complete': successful, 'utf8_valid': self._valid,
                'snapshot_complete': successful and self._valid and self._count <= snapshot_limit}
