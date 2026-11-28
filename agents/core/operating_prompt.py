"""Carry a prepared instruction prefix and its original authority separately."""

from contextlib import contextmanager
from contextvars import ContextVar

from .conversation_clock import render_snapshot

_preview: ContextVar[bool] = ContextVar("nerva_guidance_preview", default=False)


@contextmanager
def guidance_preview_scope():
    token = _preview.set(True)
    try:
        yield
    finally:
        _preview.reset(token)


def is_guidance_preview() -> bool:
    return _preview.get()


class OperatingPrompt(str):
    """Internal string accepted by backends, with no marker-based stripping."""

    def __new__(cls, content: str, *, base: str, model: str):
        prompt = super().__new__(cls, content)
        prompt.base = base
        prompt.model = model
        return prompt


class TieredSystemPrompt(OperatingPrompt):
    """H386 — ``OperatingPrompt`` carrying explicit ``(stable, context, volatile)`` tiers."""

    def __new__(
        cls,
        *,
        stable: str,
        base: str,
        model: str,
        context: str = "",
        volatile: str = "",
        identity_digest: str = "",
    ):
        prefix = "\n\n".join(part for part in (stable, context) if part)
        if prefix and volatile:
            sep = "\n" if context and volatile.startswith("Today's date (as of the last context rebuild):") else "\n\n"
            rendered = f"{prefix}{sep}{volatile}"
        else:
            rendered = prefix or volatile
        prompt = super().__new__(cls, rendered, base=base, model=model)
        prompt.stable_tier = stable
        prompt.context_tier = context
        prompt.volatile_tier = volatile
        prompt.identity_digest = identity_digest
        return prompt

    @property
    def prefix_block(self) -> str:
        return "\n\n".join(part for part in (self.stable_tier, self.context_tier) if part)

    @property
    def volatile_block(self) -> str:
        return self.volatile_tier

    def blocks(self) -> list[str]:
        prefix = self.prefix_block
        if prefix and self.volatile_tier:
            return [prefix, self.volatile_tier]
        text = str(self)
        return [text] if text else []


def original_prompt(prompt: str) -> str:
    return prompt.base if isinstance(prompt, OperatingPrompt) else prompt


def clocked_prompt(prompt: str, snapshot) -> str:
    from .prompt_tiers import split_pruned_notice, strip_clock_lines

    content = render_snapshot(prompt, snapshot)
    if isinstance(prompt, TieredSystemPrompt):
        without_notice, notice = split_pruned_notice(content)
        _body, start_line, today_line = strip_clock_lines(without_notice)
        volatile = "\n\n".join(part for part in (today_line, notice) if part)
        return TieredSystemPrompt(
            stable=prompt.stable_tier,
            base=render_snapshot(prompt.base, snapshot),
            model=prompt.model,
            context=start_line,
            volatile=volatile,
            identity_digest=prompt.identity_digest,
        )
    if isinstance(prompt, OperatingPrompt):
        return OperatingPrompt(content, base=render_snapshot(prompt.base, snapshot), model=prompt.model)
    return content
