# Extending Nerva: which seam to use (H569)

The most common contributor mistake is building against the wrong seam. This table says,
for each thing you might want to add, where it goes, whether someone outside this
repository can add it without a pull request, and what governs it. Hermes publishes the
same kind of "I want to add X" map (acp-mcp-dev.plugin-interface-map).

| I want to add… | Seam | Out-of-tree today? | Governed by |
|---|---|---|---|
| a tool the assistant can call, an owner slash command, or an observer of lifecycle events | a declarative extension (`docs/EXTENSIONS.md`; `agents/core/extensions/`) | **yes** — an author folder, a Python distribution (`nerva.extensions` entry point) or a pack, installed with `nerva extensions install` | static checks, sealed sandbox verification, an `extensions.install` approval card, consent to the declared surface, isolated activation |
| a script that runs on a lifecycle event and can block a tool call | an owner hook (`docs/HOOKS.md`; `agents/core/hooks/`) | **yes** — any program, in any language | a `hooks.define` approval card binding the argv and file hashes; `hook.exec` with the kernel on |
| a model provider (request shaping hooks, catalog) | a signed provider package (`agents/core/llm/providers/packages.py`, Console → Admin → Provider packages, `/api/llm/provider-packages/*`) | **yes** | quarantine, signature, owner admission, sandboxed hooks (`agents/core/llm/providers/hook_runtime.py`) |
| text-to-speech or speech-to-text through a local command | a config-driven command provider (`agents/core/voice/provider_registry.py`) — no Python | **yes** | owner-approved voice command settings (`settings.voice_command` card) |
| a tool server speaking MCP | an MCP server entry (`docs/MCP_CATALOG.md`; `agents/core/mcp/`) | **yes** | per-server configuration, timeouts and the tool surface's approvals |
| a skill (instructions, optionally signed code) | the skills pipeline (`docs/SKILLS_CATALOG.md`; `agents/core/skills/`) | **yes** | signing, quarantine, `skill.install` / `skill.generation` gates, skill sources (`skills.tap_add` card) |
| an image, video, web, browser or terminal backend | `ProviderBase` + `ProviderRegistry` (`agents/core/media_providers.py`) | no — in-tree only, no implicit discovery | a pull request |
| a chat platform | `ChannelAdapter` (`agents/core/channels/base.py`) | no — in-tree only | a pull request |
| a memory store | `VectorStore` (`agents/core/memory/store.py`) | no — in-tree only | a pull request |
| a model backend class (not a request-shaping package) | `LLMBackend` (`agents/core/llm/base.py`) | no — in-tree only | a pull request |
| a secret source (keychain, password manager) | none yet: `${source:…}` references other than the built-in ones stay literal (`agents/core/settings_interpolation.py`) | no | — |

## The growth contract: new methods come with defaults

An implementation written against one of the seams above must keep working when Nerva
adds a method to it. So a seam grows only through methods that have a default
implementation; the set of abstract methods each seam requires is frozen and pinned by
`tests/test_h569_seam_growth_contract.py`:

| seam | required (abstract) methods |
|---|---|
| `ProviderBase` | `name`, `kind` |
| `LLMBackend` | `generate` |
| `ChannelAdapter` | `start`, `stop`, `send` |
| `VectorStore` | `add`, `get`, `remove`, `remove_where`, `search`, `search_by_sender`, `search_by_text_subset`, `clear`, `__len__` |
| provider package hooks | required: `prepare_messages`, `build_extra_body`, `build_api_kwargs_extras`; optional (with defaults): `get_max_tokens`, `supported_reasoning_efforts` |

Adding an abstract method, or a required provider-package hook, fails that test. The
change is then deliberate: give the method a default instead, or change the fixture and
this table in the same commit and say which implementations it breaks. The test also
builds a minimal implementation of each seam with only the required methods, so a
method that loses its default is caught the same way.

What is not yet open: third-party packages cannot register a memory store, a chat
platform, a media backend, a web search backend or a secret source; those seams are
in-tree classes selected by configuration.
