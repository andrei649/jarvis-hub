"""Hostile text can never become markup in the ANDREI OS page.

Vault note titles, paths, model names and the parameters a model returns for an action
(a campaign name, an objective) are written into the page only through the builders in
`apps/jarvis-os/public/js/templates.js`. This test executes those real builders under
Node with hostile input and parses what they return: the only elements and attributes
allowed are the ones the templates themselves write.
"""
import json
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
JS = repo_root / "apps" / "jarvis-os" / "public" / "js"

HOSTILE = [
    '<img src=x onerror="alert(1)">',
    "<script>alert(1)</script>",
    '"><svg/onload=alert(1)>',
    "' onmouseover='alert(1)",
    "</td></tr></table><iframe src=javascript:alert(1)>",
    "`${alert(1)}`",
    "&lt;b&gt;already escaped&lt;/b&gt;",
]

ALLOWED = {
    "tr": {"class"}, "td": set(), "strong": set(), "span": {"class", "style"},
    "input": {"type", "checked", "data-idx"}, "div": {"class", "data-node-idx", "data-cat"},
    "option": {"value"},
}

RUNNER = """
import { pathToFileURL } from "node:url";
const [modulePath, payload] = process.argv.slice(2);
const t = await import(pathToFileURL(modulePath).href);
const hostile = JSON.parse(payload);
const out = {};
for (const text of hostile) {
  out[text] = {
    campaigns: t.campaignRowsHtml([{ on: true, isDraft: true, name: text, delivery: text,
      objective: text, budget: text, results: text, reach: text, cpr: text }]),
    hubs: t.hubRowsHtml([{ title: text, color: text, displayCount: text, nodeIndex: text }], []),
    filters: t.filterRowsHtml([{ id: text, color: text, count: text }]),
    sources: t.sourceCardsHtml([{ name: text, status: text, path: text, detail: text }]),
    models: t.modelOptionsHtml([text]),
    escaped: t.escapeHtml(text),
  };
}
process.stdout.write(JSON.stringify(out));
"""


class _Shape(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {name for name, _value in attrs}))

    def handle_data(self, data):
        self.text.append(data)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    runner = tmp_path_factory.mktemp("templates") / "run.mjs"
    runner.write_text(RUNNER, encoding="utf-8")
    result = subprocess.run([node, str(runner), str(JS / "templates.js"), json.dumps(HOSTILE)],
                            capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_text_renders_as_text_in_every_builder(rendered, text):
    for builder in ("campaigns", "hubs", "filters", "sources", "models"):
        html = rendered[text][builder]
        shape = _Shape()
        shape.feed(html)
        shape.close()
        for tag, attributes in shape.tags:
            assert tag in ALLOWED, f"{builder}: <{tag}> came from the input"
            assert attributes <= ALLOWED[tag], f"{builder}: <{tag}> gained {attributes - ALLOWED[tag]}"
        if builder != "hubs":      # hubs also print the text inside a style value
            assert text in "".join(shape.text), f"{builder}: the text itself must still be shown"


@pytest.mark.parametrize("text", HOSTILE)
def test_escape_covers_content_and_quoted_attributes(rendered, text):
    escaped = rendered[text]["escaped"]
    for raw in "<>\"'`":
        assert raw not in escaped
    shape = _Shape()
    shape.feed(f'<i title="{escaped}">{escaped}</i>')
    shape.close()
    assert shape.tags == [("i", {"title"})] and "".join(shape.text) == text


def test_every_page_script_writes_untrusted_html_through_the_builders():
    """The sinks the review named now delegate; no other file builds these tables."""
    cu = (JS / "computer-use.js").read_text(encoding="utf-8")
    assert "this.tbody.innerHTML = campaignRowsHtml(this.campaigns);" in cu
    assert "${c.name}" not in cu and "${c.objective}" not in cu
    main = (JS / "main.js").read_text(encoding="utf-8")
    for call in ("hubRowsHtml(hubs, this.dataset.nodes)", "filterRowsHtml(cats)",
                 "sourceCardsHtml(sources)", "modelOptionsHtml(oll.models)"):
        assert call in main
    for raw in ("${h.title}", "${c.id}", "${s.name}", "${s.path}", "${m}"):
        assert raw not in main


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
