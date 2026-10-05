"""Importable tools over the existing sandbox RPC, with the same offered ceiling.

Adapted from Hermes generate_hermes_tools_module / per-tool stub templates,
59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e/tools/code_execution_tool.py.
Copyright (c) 2025 Nous Research, MIT; see
docs/hermes/licenses/hermes-code-execution-MIT.txt.

Nerva derives signatures from its live registry instead of a second hardcoded
tool list. Helpers return the existing RPC envelope, including approval/refusal,
and call the same broker. No credentials or host modules enter the child.
"""

from __future__ import annotations

import keyword
from collections.abc import Mapping, Sequence


def _identifier(value: object) -> bool:
    return isinstance(value, str) and value.isidentifier() and not keyword.iskeyword(value)


def tool_import_source(tools: Sequence[Mapping[str, object]], offered: frozenset[str]) -> str:
    """Install a fresh jarvis_tools module without adding a child filesystem mount.

    A saved function uses the current jarvis_tool_call/broker, so its old export
    does not keep the right to a tool that the next invocation no longer offers.
    Arbitrary strings in registry schemas are quoted; only Python identifiers
    become syntax. Optional arguments omitted by the caller remain omitted.
    """
    functions = []
    names = []
    rows = [row for row in tools if row.get("name") in offered
            and _identifier(row.get("name")) and not row["name"].startswith("_")]
    used = {row["name"] for row in rows}
    for row in rows:
        used.update((row.get("input_schema") or {}).get("properties", {}))

    def private(stem):
        while stem in used:
            stem += "_"
        used.add(stem)
        return stem

    missing, rpc = private("_jarvis_missing"), private("_jarvis_rpc")
    for row in rows:
        name = row["name"]
        schema = row.get("input_schema") or {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        fields = [key for key in properties if _identifier(key)]
        # Private generated identifiers must never collide with a schema field.
        extra = private("_jarvis_extra")
        ordered = [key for key in fields if key in required] + [key for key in fields if key not in required]
        signature = ", ".join(key if key in required else f"{key}={missing}" for key in ordered)
        signature = f"{signature}, **{extra}" if signature else f"**{extra}"
        payload = ", ".join(f"{key!r}: {key}" for key in ordered)
        functions.append(
            f"def {name}({signature}):\n"
            f"    return {rpc}({name!r}, {{**{extra}, **{{k: v for k, v in "
            f"{{{payload}}}.items() if v is not {missing}}}}})\n"
        )
        names.append(name)
    source = f"{missing} = object()\n" + "\n".join(functions) + f"\n__all__ = {names!r}\n"
    return (
        "import sys as _jarvis_stub_sys\n"
        "import types as _jarvis_stub_types\n"
        "_jarvis_stub_module = _jarvis_stub_types.ModuleType('jarvis_tools')\n"
        f"_jarvis_stub_module.__dict__[{rpc!r}] = jarvis_tool_call\n"
        f"exec({source!r}, _jarvis_stub_module.__dict__)\n"
        "_jarvis_stub_sys.modules['jarvis_tools'] = _jarvis_stub_module\n"
    )
