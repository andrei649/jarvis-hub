"""Call-scoped token observation without changing public backend signatures."""
import logging
from contextlib import contextmanager
from contextvars import ContextVar

from .tool_protocol import TokenUsage

logger = logging.getLogger(__name__)
_observer: ContextVar = ContextVar('llm_usage_observer', default=None)
_publisher: ContextVar = ContextVar('llm_text_usage_publisher', default=None)


class _Observer:
    def __init__(self, sink):
        self.sink = sink
        self.active = True

    def __call__(self, usage: TokenUsage) -> None:
        if not self.active or self.sink is None or not usage.reported:
            return
        try:
            self.sink(usage)
        except Exception:
            logger.warning('usage sink failed', exc_info=True)

    def close(self):
        self.active = False
        self.sink = None


@contextmanager
def _scope(variable, sink):
    observer = _Observer(sink)
    token = variable.set(observer)
    try:
        yield observer
    finally:
        observer.close()
        variable.reset(token)


def observer_scope(sink):
    """Bind trusted caller observation; does not enable backend publication."""
    return _scope(_observer, sink)


def current_observer():
    return _observer.get()


def text_usage_scope(sink):
    """Enable only the legacy generation branch; inherited tasks expire on exit."""
    return _scope(_publisher, sink)


def report_text_usage(usage: TokenUsage) -> None:
    observer = _publisher.get()
    if observer is not None:
        observer(usage)
