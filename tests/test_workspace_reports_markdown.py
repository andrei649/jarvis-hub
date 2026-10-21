"""The escaping Markdown → HTML renderer behind report exports and emails (spec §7 export).

It must render the Markdown a model writes for a report — headings, paragraphs, nested
lists, tables, bold/italic, code and http(s) links — and escape everything else, so no
model output or document text can put markup, script or a ``javascript:`` link into an
exported page or an email.
"""

from __future__ import annotations

import pytest

from agents.core.workspace.reports import html_page, render_inline, render_markdown, safe_url


def test_headings_paragraphs_and_soft_line_breaks():
    html = render_markdown("# Raport lunar\n\nPrima linie\na doua linie.\n\n### Detalii ###")
    assert html == ("<h1>Raport lunar</h1>\n<p>Prima linie a doua linie.</p>\n"
                    "<h3>Detalii</h3>")


def test_strong_emphasis_and_code_are_well_nested():
    assert render_inline("**Vânzări** și *creștere* și `cod <b>`") == (
        "<strong>Vânzări</strong> și <em>creștere</em> și <code>cod &lt;b&gt;</code>")
    assert render_inline("__bold__ and _it_") == "<strong>bold</strong> and <em>it</em>"
    assert render_inline("**a *b* c**") == "<strong>a <em>b</em> c</strong>"
    # Unbalanced markers stay text and never produce crossed tags.
    assert render_inline("***x***") == "<strong>*x</strong>*"


def test_intraword_markers_stay_literal():
    assert render_inline("snake_case_name and 2*3*4") == "snake_case_name and 2*3*4"


def test_raw_html_is_escaped_everywhere():
    html = render_markdown('<script>alert(1)</script>\n\n<img src=x onerror="a()">')
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=&quot;a()&quot;&gt;" in html


@pytest.mark.parametrize("url", ["https://firma.ro/raport?a=1&b=2", "http://example.com/x"])
def test_http_links_render_with_escaped_href(url):
    html = render_inline(f"vezi [pagina]({url})")
    assert html.startswith('vezi <a href="')
    assert 'rel="noopener noreferrer">pagina</a>' in html
    assert "&amp;b=2" in html or "&" not in url


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,x", "vbscript:x", "//evil.example/x", "/relative",
    "mailto:a@b.ro", "https://", "https://x.ro/\"onmouseover=", "http://[::1",
])
def test_other_links_are_shown_as_text(url):
    html = render_inline(f"[click]({url})")
    assert "<a " not in html
    assert "click" in html
    assert safe_url(url) is None


def test_link_text_keeps_emphasis_and_escapes():
    assert render_inline("[**<Sursa>**](https://a.ro)") == (
        '<a href="https://a.ro" rel="noopener noreferrer"><strong>&lt;Sursa&gt;</strong></a>')


def test_unordered_ordered_and_nested_lists():
    text = "- unu\n- doi\n  - doi.a\n  - doi.b\n- trei\n\n3. trei\n4. patru"
    assert render_markdown(text) == (
        "<ul><li>unu</li><li>doi<ul><li>doi.a</li><li>doi.b</li></ul></li><li>trei</li></ul>"
        '<ol start="3"><li>trei</li><li>patru</li></ol>')


def test_list_continuation_and_loose_items():
    text = "1. Primul punct\n   continuat aici\n\n2. Al doilea"
    assert render_markdown(text) == (
        "<ol><li>Primul punct continuat aici</li><li>Al doilea</li></ol>")


def test_switching_list_type_at_the_same_level_closes_the_list():
    assert render_markdown("- a\n1. b") == "<ul><li>a</li></ul><ol><li>b</li></ol>"


def test_tables_with_alignment_inline_markup_and_ragged_rows():
    text = ("| Produs | Cantitate | Total |\n|:---|---:|:---:|\n| **Laptop** | 3 | 9 000 lei |\n"
            "| Mouse | 10 |\n| a \\| b | 1 | 2 | extra |")
    html = render_markdown(text)
    assert html.startswith("<table><thead><tr><th>Produs</th>"
                           '<th style="text-align:right">Cantitate</th>'
                           '<th style="text-align:center">Total</th></tr></thead><tbody>')
    assert "<td><strong>Laptop</strong></td>" in html
    assert '<td>Mouse</td><td style="text-align:right">10</td><td style="text-align:center"></td>' in html
    assert "<td>a | b</td>" in html and "extra" not in html


def test_a_pipe_in_a_paragraph_is_not_a_table():
    assert render_markdown("a | b\n\nc") == "<p>a | b</p>\n<p>c</p>"


def test_fenced_code_keeps_text_verbatim_and_escaped():
    html = render_markdown("```python\nif a < b:\n    print('**x**')\n```\nDupă")
    assert html == ("<pre><code>if a &lt; b:\n    print(&#x27;**x**&#x27;)</code></pre>\n"
                    "<p>După</p>")


def test_unterminated_fence_runs_to_the_end():
    assert render_markdown("~~~\ncod") == "<pre><code>cod</code></pre>"


def test_horizontal_rules_and_citation_markers():
    assert render_markdown("Text [1][2]\n\n---\n\n* * *") == "<p>Text [1][2]</p>\n<hr>\n<hr>"


def test_crlf_input_and_empty_input():
    assert render_markdown("# T\r\n\r\nx") == "<h1>T</h1>\n<p>x</p>"
    assert render_markdown("") == ""


def test_html_page_is_standalone_print_ready_and_script_free():
    page = html_page(title="Raport <x>", lang="ro", header="<p>h</p>", body="<p>b</p>",
                     footer="<p>f</p>")
    assert page.startswith("<!doctype html>\n<html lang=\"ro\">")
    assert "<title>Raport &lt;x&gt;</title>" in page
    assert '<meta charset="utf-8">' in page and "@media print" in page and "@page" in page
    assert "<script" not in page.lower() and "<link" not in page.lower()


def test_renders_a_realistic_model_report():
    report = (
        "# Raport săptămânal vânzări\n\n## Rezumat executiv\n\nVânzările au crescut cu **12%** [1].\n\n"
        "## Detalii\n\n| Regiune | Valoare |\n|---|---|\n| Nord | 120 000 |\n\n"
        "## Surse\n\n- [1] Raport Nord\n- [2] Ghid\n"
    )
    html = render_markdown(report)
    assert html.count("<h2>") == 3
    assert "<strong>12%</strong> [1]" in html
    assert "<li>[1] Raport Nord</li>" in html
