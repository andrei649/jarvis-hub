"""registry.py — the language servers Nerva knows (H055/H564/H597).

One row per server: what it serves (extensions, basenames and the LSP language id
for each), how it is started (argv after the binary), which binary names discover
it, and the install recipe — a pinned package on one package registry, or a
``manual`` hint when the server ships through a toolchain Nerva does not drive
(rustup, the system package manager).

The rows are data. Nothing here runs anything: discovery is :mod:`.manager`,
installs are :mod:`.install` (an approval card first), spawning is :mod:`.client`
under :mod:`.confine`.

Pins are exact versions of the top-level package. Each registry resolves its own
transitive dependencies (npm and pip are not lockfile-pinned below the top level;
``go install`` verifies every module against the Go checksum database).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath

#: The package registries an install may reach, by recipe kind.
REGISTRIES: dict[str, str] = {
    "npm": "https://registry.npmjs.org/",
    "pip": "https://pypi.org/simple",
    "go": "https://proxy.golang.org",
}


@dataclass(frozen=True)
class Recipe:
    """How an approved install fetches a server.

    ``kind`` is ``npm``, ``pip``, ``go`` or ``manual``. ``packages`` are exact pins
    (``name@1.2.3`` for npm and go, ``name==1.2.3`` for pip). ``manual`` carries a
    human hint and is never run by Nerva.
    """

    kind: str
    packages: tuple[str, ...] = ()
    hint: str = ""

    @property
    def installable(self) -> bool:
        return self.kind in REGISTRIES and bool(self.packages)

    @property
    def version(self) -> str:
        if not self.packages:
            return ""
        first = self.packages[0]
        for sep in ("==", "@"):
            if sep in first.lstrip("@"):
                return first.rsplit(sep, 1)[1]
        return ""


@dataclass(frozen=True)
class ServerSpec:
    id: str
    name: str
    binaries: tuple[str, ...]
    args: tuple[str, ...]
    #: extension (lower-case, with the dot) → LSP language id
    extensions: dict[str, str]
    recipe: Recipe
    basenames: dict[str, str] = field(default_factory=dict)

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.extensions.values()) | set(self.basenames.values())))

    def language_for(self, path: PurePath) -> str | None:
        if path.name in self.basenames:
            return self.basenames[path.name]
        return self.extensions.get(path.suffix.lower())


_TS = {".ts": "typescript", ".tsx": "typescriptreact", ".mts": "typescript", ".cts": "typescript",
       ".js": "javascript", ".jsx": "javascriptreact", ".mjs": "javascript", ".cjs": "javascript"}
_C = {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
      ".hxx": "cpp"}

#: In preference order: the first available server for an extension serves it.
SERVERS: tuple[ServerSpec, ...] = (
    ServerSpec(
        id="pyright", name="Pyright", binaries=("pyright-langserver",), args=("--stdio",),
        extensions={".py": "python", ".pyi": "python"},
        recipe=Recipe("npm", ("pyright@1.1.389",)),
    ),
    ServerSpec(
        id="pylsp", name="python-lsp-server", binaries=("pylsp",), args=(),
        extensions={".py": "python", ".pyi": "python"},
        recipe=Recipe("pip", ("python-lsp-server==1.12.0",)),
    ),
    ServerSpec(
        id="typescript", name="typescript-language-server", binaries=("typescript-language-server",),
        args=("--stdio",), extensions=_TS,
        recipe=Recipe("npm", ("typescript-language-server@4.3.3", "typescript@5.6.3")),
    ),
    ServerSpec(
        id="gopls", name="gopls", binaries=("gopls",), args=("serve",),
        extensions={".go": "go"}, basenames={"go.mod": "go.mod"},
        recipe=Recipe("go", ("golang.org/x/tools/gopls@v0.16.2",)),
    ),
    ServerSpec(
        id="rust-analyzer", name="rust-analyzer", binaries=("rust-analyzer",), args=(),
        extensions={".rs": "rust"},
        recipe=Recipe("manual", hint="install with `rustup component add rust-analyzer`"),
    ),
    ServerSpec(
        id="clangd", name="clangd", binaries=("clangd",), args=("--background-index=false",),
        extensions=_C,
        recipe=Recipe("manual", hint="install clangd from your system package manager"),
    ),
    ServerSpec(
        id="bash", name="bash-language-server", binaries=("bash-language-server",), args=("start",),
        extensions={".sh": "shellscript", ".bash": "shellscript"},
        recipe=Recipe("npm", ("bash-language-server@5.4.0",)),
    ),
    ServerSpec(
        id="yaml", name="yaml-language-server", binaries=("yaml-language-server",), args=("--stdio",),
        extensions={".yaml": "yaml", ".yml": "yaml"},
        recipe=Recipe("npm", ("yaml-language-server@1.15.0",)),
    ),
    ServerSpec(
        id="json", name="vscode-json-language-server", binaries=("vscode-json-language-server",),
        args=("--stdio",), extensions={".json": "json", ".jsonc": "jsonc"},
        recipe=Recipe("npm", ("vscode-langservers-extracted@4.10.0",)),
    ),
    ServerSpec(
        id="css", name="vscode-css-language-server", binaries=("vscode-css-language-server",),
        args=("--stdio",), extensions={".css": "css", ".scss": "scss", ".less": "less"},
        recipe=Recipe("npm", ("vscode-langservers-extracted@4.10.0",)),
    ),
    ServerSpec(
        id="html", name="vscode-html-language-server", binaries=("vscode-html-language-server",),
        args=("--stdio",), extensions={".html": "html", ".htm": "html"},
        recipe=Recipe("npm", ("vscode-langservers-extracted@4.10.0",)),
    ),
    ServerSpec(
        id="dockerfile", name="dockerfile-language-server", binaries=("docker-langserver",), args=("--stdio",),
        extensions={".dockerfile": "dockerfile"}, basenames={"Dockerfile": "dockerfile"},
        recipe=Recipe("npm", ("dockerfile-language-server-nodejs@0.14.0",)),
    ),
    # Discovery only: these ship through their own toolchains, which Nerva does not drive.
    ServerSpec(id="lua", name="lua-language-server", binaries=("lua-language-server",), args=(),
               extensions={".lua": "lua"},
               recipe=Recipe("manual", hint="install lua-language-server from its releases or your package manager")),
    ServerSpec(id="jdtls", name="Eclipse JDT LS", binaries=("jdtls",), args=(), extensions={".java": "java"},
               recipe=Recipe("manual", hint="install jdtls (Eclipse JDT Language Server) with your package manager")),
    ServerSpec(id="kotlin", name="kotlin-language-server", binaries=("kotlin-language-server",), args=(),
               extensions={".kt": "kotlin", ".kts": "kotlin"},
               recipe=Recipe("manual", hint="install kotlin-language-server from its releases")),
    ServerSpec(id="csharp", name="csharp-ls", binaries=("csharp-ls",), args=(), extensions={".cs": "csharp"},
               recipe=Recipe("manual", hint="install with `dotnet tool install --global csharp-ls`")),
    ServerSpec(id="ruby", name="ruby-lsp", binaries=("ruby-lsp",), args=(), extensions={".rb": "ruby"},
               basenames={"Gemfile": "ruby", "Rakefile": "ruby"},
               recipe=Recipe("manual", hint="install with `gem install ruby-lsp`")),
    ServerSpec(id="elixir", name="ElixirLS", binaries=("elixir-ls", "language_server.sh"), args=(),
               extensions={".ex": "elixir", ".exs": "elixir"},
               recipe=Recipe("manual", hint="install elixir-ls from its releases")),
    ServerSpec(id="zls", name="zls", binaries=("zls",), args=(), extensions={".zig": "zig"},
               recipe=Recipe("manual", hint="install zls matching your Zig version")),
    ServerSpec(id="haskell", name="haskell-language-server", binaries=("haskell-language-server-wrapper",),
               args=("--lsp",), extensions={".hs": "haskell", ".lhs": "lhaskell"},
               recipe=Recipe("manual", hint="install with `ghcup install hls`")),
    ServerSpec(id="ocaml", name="ocaml-lsp", binaries=("ocamllsp",), args=(), extensions={".ml": "ocaml", ".mli": "ocaml"},
               recipe=Recipe("manual", hint="install with `opam install ocaml-lsp-server`")),
    ServerSpec(id="terraform", name="terraform-ls", binaries=("terraform-ls",), args=("serve",),
               extensions={".tf": "terraform", ".tfvars": "terraform-vars"},
               recipe=Recipe("manual", hint="install terraform-ls from HashiCorp's releases")),
    ServerSpec(id="swift", name="sourcekit-lsp", binaries=("sourcekit-lsp",), args=(), extensions={".swift": "swift"},
               recipe=Recipe("manual", hint="sourcekit-lsp ships with the Swift toolchain")),
)

BY_ID: dict[str, ServerSpec] = {spec.id: spec for spec in SERVERS}


def spec(server_id: object) -> ServerSpec | None:
    return BY_ID.get(server_id) if isinstance(server_id, str) else None


def candidates_for(path: PurePath) -> list[tuple[ServerSpec, str]]:
    """Every server that serves *path*, in preference order, with its language id."""
    found = []
    for row in SERVERS:
        language = row.language_for(path)
        if language:
            found.append((row, language))
    return found


__all__ = ["BY_ID", "REGISTRIES", "Recipe", "SERVERS", "ServerSpec", "candidates_for", "spec"]
