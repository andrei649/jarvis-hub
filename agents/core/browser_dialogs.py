"""Ephemeral native-dialog evidence; it confers no actuation authority."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urldefrag

_TYPES = frozenset({'alert', 'confirm', 'prompt', 'beforeunload'})
_TEXT_LIMIT = 1024


@dataclass(frozen=True)
class ObservedDialog:
    dialog: object
    frame_id: str
    loader_id: str
    document_epoch: int
    kind: str
    message: str
    default_value: str


class DialogFrameObserver:
    """Pair one Playwright dialog with one internal CDP Page event.

    A match is only evidence of the owned main frame during the armed browser
    operation. It cannot prove which page script produced the event.
    """

    def __init__(self, *, page: object) -> None:
        self.page = page
        self.root_frame_id = ''
        self.loader_id = ''
        self.frame_url = ''
        self.document_epoch = -1
        self.refused_reason = ''
        self._armed = False
        self._cdp: tuple[str, str, str] | None = None
        self._playwright: object | None = None
        self._paired: ObservedDialog | None = None

    def arm(self, *, root_frame_id: str, loader_id: str,
            frame_url: str, document_epoch: int) -> None:
        if (not root_frame_id or not loader_id or not frame_url
                or type(document_epoch) is not int or document_epoch < 0):
            self.refuse('dialog_frame_unknown')
            return
        self.root_frame_id = root_frame_id
        self.loader_id = loader_id
        self.frame_url = urldefrag(frame_url).url
        self.document_epoch = document_epoch
        self.refused_reason = ''
        self._cdp = None
        self._playwright = None
        self._paired = None
        self._armed = True

    def refuse(self, reason: str = 'dialog_frame_unknown') -> None:
        self.refused_reason = reason
        self._armed = False
        self._cdp = None
        self._playwright = None
        self._paired = None

    def invalidate(self) -> None:
        self.refuse('dialog_document_changed')

    def on_cdp_open(self, event: object) -> None:
        if not self._armed or self._cdp is not None or self._paired is not None:
            self.refuse()
            return
        if not isinstance(event, dict):
            self.refuse()
            return
        frame_id, url = event.get('frameId'), event.get('url')
        kind, message = event.get('type'), event.get('message')
        default = event.get('defaultPrompt', '')
        if (type(frame_id) is not str or frame_id != self.root_frame_id
                or type(url) is not str or urldefrag(url).url != self.frame_url
                or kind not in _TYPES or type(message) is not str
                or len(message) > _TEXT_LIMIT or type(default) is not str
                or len(default) > _TEXT_LIMIT):
            self.refuse()
            return
        self._cdp = (kind, message, default)
        self._try_pair()

    def on_playwright_dialog(self, dialog: object) -> None:
        if not self._armed or self._playwright is not None or self._paired is not None:
            self.refuse()
            return
        try:
            page, kind = dialog.page, dialog.type
            message, default = dialog.message, dialog.default_value
        except Exception:
            self.refuse()
            return
        if (page is not self.page or kind not in _TYPES
                or type(message) is not str or len(message) > _TEXT_LIMIT
                or type(default) is not str or len(default) > _TEXT_LIMIT):
            self.refuse()
            return
        self._playwright = dialog
        self._try_pair()

    def _try_pair(self) -> None:
        if self._cdp is None or self._playwright is None:
            return
        dialog = self._playwright
        if self._cdp != (dialog.type, dialog.message, dialog.default_value):
            self.refuse()
            return
        self._paired = ObservedDialog(
            dialog, self.root_frame_id, self.loader_id, self.document_epoch,
            dialog.type, dialog.message, dialog.default_value,
        )

    def pending(self) -> ObservedDialog | None:
        return self._paired if self._armed and not self.refused_reason else None
