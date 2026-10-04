"""Carry a prepared instruction prefix and its original authority separately."""

from .conversation_clock import render_snapshot


class OperatingPrompt(str):
    """Internal string accepted by backends, with no marker-based stripping."""

    def __new__(cls, content: str, *, base: str, model: str):
        prompt = super().__new__(cls, content)
        prompt.base = base
        prompt.model = model
        return prompt


def original_prompt(prompt: str) -> str:
    return prompt.base if isinstance(prompt, OperatingPrompt) else prompt


def clocked_prompt(prompt: str, snapshot) -> str:
    content = render_snapshot(prompt, snapshot)
    if isinstance(prompt, OperatingPrompt):
        return OperatingPrompt(content, base=render_snapshot(prompt.base, snapshot), model=prompt.model)
    return content
