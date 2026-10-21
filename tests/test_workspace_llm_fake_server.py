"""The fake OpenAI-compatible model server used by the integration tests and the e2e run.

It must speak the wire format the hub's ``lm-studio`` backend expects, answer
deterministically (citing ``[1]``, in the question's language, a Markdown report when
asked for one), simulate trouble on demand, and run as a script that prints ``READY``.
"""

from __future__ import annotations

import json
import math
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.support import fake_openai_server as fake
from tests.support.fake_openai_server import FakeOpenAIServer

SCRIPT = Path(fake.__file__)
SOURCES = ('<source id="1" title="Politica de concedii">Concediul anual este de 21 de zile. '
           "Se cere din timp.</source>\n\n"
           '<source id="2" title="Vânzări T3">Vânzările au crescut cu 12% | față de T2.'
           "</source>\n\n")


@pytest.fixture
def server():
    with FakeOpenAIServer(slow_seconds=3.0) as running:
        yield running


def _chat(server: FakeOpenAIServer, prompt: str, *, system: str = "", stream: bool = False,
          timeout: float = 5.0) -> httpx.Response:
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    return httpx.post(f"{server.url}/v1/chat/completions", timeout=timeout,
                      json={"model": "m", "messages": messages, "stream": stream})


def _streamed_text(response: httpx.Response) -> tuple[str, list[str]]:
    lines = [line for line in response.text.split("\n") if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line[6:]) for line in lines[:-1]]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    pieces = [c["choices"][0]["delta"].get("content", "") for c in chunks]
    return "".join(pieces), [p for p in pieces if p]


# ── the wire format ──────────────────────────────────────────────────────────────────

def test_models_lists_the_configured_model(server):
    response = httpx.get(f"{server.url}/v1/models", timeout=5)
    assert response.json()["data"] == [{"id": fake.DEFAULT_MODEL, "object": "model"}]


def test_a_non_streamed_completion_has_the_openai_shape(server):
    data = _chat(server, SOURCES + "Întrebarea utilizatorului:\nCâte zile de concediu avem?").json()
    assert data["object"] == "chat.completion"
    choice = data["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == \
        "Conform documentelor companiei: Concediul anual este de 21 de zile. [1]"
    assert data["usage"]["total_tokens"] > 0


def test_a_streamed_completion_is_chunked_deltas_then_done(server):
    response = _chat(server, SOURCES + "User question:\nHow many leave days do we have?",
                     stream=True)
    assert response.headers["content-type"].startswith("text/event-stream")
    text, pieces = _streamed_text(response)
    assert text == "According to the company documents: Concediul anual este de 21 de zile. [1]"
    assert len(pieces) > 3


def test_the_server_records_what_it_was_sent(server):
    _chat(server, "Salut", system="Ești asistentul.")
    assert server.requests[-1]["path"] == "/v1/chat/completions"
    assert server.requests[-1]["body"]["messages"][0]["content"] == "Ești asistentul."


def test_unknown_paths_and_bad_bodies_are_refused(server):
    assert httpx.get(f"{server.url}/v2/nothing", timeout=5).status_code == 404
    assert httpx.post(f"{server.url}/v1/chat/completions", content=b"{not json",
                      headers={"Content-Type": "application/json"}, timeout=5).status_code == 400
    assert httpx.post(f"{server.url}/v1/chat/completions", json=[1, 2],
                      timeout=5).status_code == 400
    assert httpx.get(f"{server.url}/health", timeout=5).json() == {"ok": True}


# ── answers ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question,expected", [
    ("Câte zile de concediu avem?", "Nu am găsit această informație în documentele companiei."),
    ("How many leave days do we have?", "I could not find this in the company documents."),
])
def test_without_sources_it_says_it_found_nothing_in_the_questions_language(question, expected):
    assert fake.compose_reply("", f"Întrebarea utilizatorului:\n{question}") == expected


def test_the_question_is_read_after_its_marker_not_from_the_sources():
    prompt = SOURCES + "Conversația de până acum:\nUtilizator: Salut ce faci\n\n" \
                       "User question:\nWhat about the summer?"
    assert fake.question_of(prompt) == "What about the summer?"
    assert fake.compose_reply("", prompt).startswith("According to the company documents:")


def test_a_report_request_gets_a_well_formed_markdown_report():
    report = fake.compose_reply("Scrii un raport structurat în Markdown.",
                                SOURCES + "Rezumă vânzările și concediile pentru conducere.")
    lines = report.splitlines()
    assert lines[0] == "# Raport: Rezumă vânzările și concediile pentru conducere"
    headings = [line for line in lines if line.startswith("## ")]
    assert headings == ["## Rezumat executiv", "## Constatări", "## Date cheie", "## Surse"]
    table = [line for line in lines if line.startswith("|")]
    assert table[0] == "| Nr. | Document | Extras |" and table[1] == "| --- | --- | --- |"
    assert len(table) == 4 and all(line.count("|") == 4 for line in table)
    assert "1. [1] Politica de concedii" in report and "2. [2] Vânzări T3" in report
    assert "[1]" in report.split("## Constatări")[0]


@pytest.mark.parametrize(("locale", "name", "ask", "empty", "heading"), [
    ("ro", "Vânzări lunare Nord", "Rezumă vânzările.", "Gol", "# Raport: Vânzări lunare Nord"),
    ("en", "Monthly sales North", "Summarize the sales.", "Empty", "# Report: Monthly sales North"),
])
def test_the_heading_of_a_real_report_prompt_names_the_report_once(locale, name, ask, empty,
                                                                     heading):
    """The workspace prompt says "Raport: <name>" itself; the heading must not repeat it."""
    from agents.core.workspace import reports

    def prompt(sources: str, report_name: str) -> str:
        return reports.report_prompt(locale, sources=sources, name=report_name, instructions=ask,
                                     date="2026-10-17", timezone="Europe/Bucharest")

    system = reports.system_prompt(locale, org="Acme", department="Vânzări", guidance="")
    report = fake.compose_reply(system, prompt(SOURCES, name))
    assert report.splitlines()[0] == heading
    assert "Raport: Raport" not in report and "Report: Report" not in report
    assert fake.compose_reply(system, prompt(SOURCES, name)) == report, "deterministic"
    without_sources = fake.compose_reply(system, prompt("", empty))
    assert without_sources.splitlines()[0] == f"{heading.split(':')[0]}: {empty}"


def test_an_english_report_without_sources_says_there_is_no_data():
    report = fake.compose_reply("You write a report.", "Summarize the quarter for the board.")
    assert report.startswith("# Report: Summarize the quarter for the board")
    assert "No data was found in the selected documents." in report
    assert "| ---" not in report


def test_the_connectivity_check_is_answered_ok():
    assert fake.compose_reply("You are a connectivity check.",
                              "Reply with the single word OK.") == "OK"


def test_pieces_reassemble_exactly():
    text = "Unu  doi\ntrei [1]."
    assert "".join(fake.pieces(text)) == text


# ── trouble on demand ────────────────────────────────────────────────────────────────

def test_the_error_trigger_answers_500(server):
    assert _chat(server, f"{fake.ERROR_TRIGGER} x").status_code == 500


def test_the_empty_trigger_answers_an_empty_completion(server):
    text, pieces = _streamed_text(_chat(server, fake.EMPTY_TRIGGER, stream=True))
    assert text == "" and pieces == []


def test_the_slow_trigger_waits_and_stopping_releases_it(server):
    started = time.monotonic()
    with pytest.raises(httpx.ReadTimeout):
        _chat(server, f"{fake.SLOW_TRIGGER} x", timeout=0.3)
    assert time.monotonic() - started < 2
    server.stop()  # returns at once although a slow answer is still "thinking"


def test_stopping_drops_kept_alive_connections():
    with FakeOpenAIServer() as running, httpx.Client(base_url=running.url, timeout=2) as client:
        assert client.get("/v1/models").status_code == 200
        running.stop()
        with pytest.raises(httpx.TransportError):
            client.get("/v1/models")


# ── embeddings ───────────────────────────────────────────────────────────────────────

def test_embeddings_are_deterministic_unit_vectors(server):
    response = httpx.post(f"{server.url}/v1/embeddings", timeout=5,
                          json={"model": "m", "input": ["Concediu anual", "concediu ANUAL", ""]})
    data = response.json()["data"]
    vectors = [item["embedding"] for item in data]
    assert [item["index"] for item in data] == [0, 1, 2]
    assert all(len(v) == fake.EMBEDDING_DIMENSIONS for v in vectors)
    assert vectors[0] == vectors[1]
    assert all(math.isclose(sum(x * x for x in v), 1.0) for v in vectors)
    single = httpx.post(f"{server.url}/v1/embeddings", timeout=5,
                        json={"input": "Concediu anual"}).json()["data"]
    assert single[0]["embedding"] == vectors[0]


# ── as a script ──────────────────────────────────────────────────────────────────────

def test_the_script_prints_ready_serves_and_stops_on_sigterm():
    process = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--port", "0"], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        assert process.stdout is not None and process.stderr is not None
        assert process.stdout.readline().strip() == "READY"
        address = re.search(r"http://127\.0\.0\.1:\d+", process.stderr.readline())
        assert address is not None
        models = httpx.get(f"{address.group(0)}/v1/models", timeout=5).json()
        assert models["data"][0]["id"] == fake.DEFAULT_MODEL
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


# ── review fix T-FIX-1: reports read like prose, not like flattened Markdown ────────────

def _real_sources(*bodies: tuple[str, str]) -> str:
    """A sources block exactly as the workspace builds it (line breaks kept)."""
    from types import SimpleNamespace

    from agents.core.workspace import assistant

    passages = [SimpleNamespace(text=text, title=title, document_id=n, chunk_id=n, page=None)
                for n, (title, text) in enumerate(bodies, start=1)]
    return assistant.build_sources_block(passages, locale="ro")[0]


def _extracted(data: bytes, kind: str) -> str:
    from agents.core.workspace import extract

    return "\n\n".join(segment.text for segment in extract.extract_bytes(data, kind).segments)


def test_a_spreadsheet_source_reads_as_its_first_row_not_as_table_syntax():
    from tests.fixtures.workspace.samples import build_xlsx

    sheet = _extracted(build_xlsx({"Încasări": [["Lună", "Județ", "Încasări (lei)"],
                                                ["Iulie", "Sibiu", 41250],
                                                ["August", "Constanța", 38900.5]]}), "xlsx")
    assert sheet.startswith("## Încasări\n\n| Lună |"), "the extractor's real shape"
    prompt = _real_sources(("incasari-trimestrul-3", sheet)) + \
        "\n\nÎntrebarea utilizatorului:\nRezumă încasările pe trimestru."
    report = fake.compose_reply("Scrii un raport structurat în Markdown.", prompt)
    summary = report.split("## Rezumat executiv", 1)[1].split("## Constatări", 1)[0]
    findings = report.split("## Constatări", 1)[1].split("## Date cheie", 1)[0]
    data = report.split("## Date cheie", 1)[1].split("## Surse", 1)[0]
    row = "Lună: Iulie — Județ: Sibiu — Încasări (lei): 41250"
    assert summary.strip() == f"{row} [1]"
    assert findings.strip() == f"- {row} [1]"
    assert "| [1] | incasari-trimestrul-3 | Lună: Iulie — Județ: Sibiu" in data
    for section in (summary, findings):
        assert "|" not in section and "##" not in section and "---" not in section
    answer = fake.compose_reply("", prompt.replace("Rezumă încasările pe trimestru.",
                                                   "Cât am încasat în iulie?"))
    assert answer == f"Conform documentelor companiei: {row} [1]"


def test_headings_are_skipped_for_the_first_prose_sentence():
    from tests.fixtures.workspace.samples import build_docx, docx_paragraph, docx_table

    body = ("# Politica de concedii — Acme SRL\n\n## Concediul de odihnă\n\n"
            "Angajații au dreptul la 21 de zile lucrătoare pe an. Cererea se face din timp.")
    docx = _extracted(build_docx(docx_paragraph("Discountul maxim este de 12% din comandă.")
                                 + docx_table([["Categorie", "Discount"], ["Client nou", "12%"]])),
                      "docx")
    csv = _extracted("Client;Oraș\nȚesătoria Mureș;Târgu Mureș\n".encode(), "csv")
    prompt = _real_sources(("Politica de concedii", body), ("politica-discount", docx),
                           ("clienti-cheie", csv)) + "\n\nRezumă documentele pentru conducere."
    report = fake.compose_reply("Scrii un raport.", prompt)
    findings = report.split("## Constatări", 1)[1].split("## Date cheie", 1)[0].strip().splitlines()
    assert findings == ["- Angajații au dreptul la 21 de zile lucrătoare pe an. [1]",
                        "- Discountul maxim este de 12% din comandă. [2]",
                        "- Client: Țesătoria Mureș — Oraș: Târgu Mureș [3]"]


def test_a_source_with_only_a_heading_or_an_escaped_pipe_still_reads_well():
    assert fake.gist("## Doar un titlu") == "Doar un titlu"
    assert fake.gist("| Cod | Preț \\| lei |\n| --- | --- |\n| A1 | 12,5 |") == \
        "Cod: A1 — Preț | lei: 12,5"
    assert fake.gist("| Total | | 100 |\n| --- | --- | --- |\n| a | b | |") == "Total: a — b"
    assert fake.gist("") == ""
