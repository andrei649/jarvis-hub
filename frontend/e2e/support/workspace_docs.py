"""Write the Romanian sample documents the Workspace journey uploads (DOCX, PDF, XLSX, CSV).

The bytes come from the same builders the backend's knowledge-base tests use
(``tests/fixtures/workspace/samples.py``: real OOXML packages, a PDF whose Type 1 font carries
a ``ToUnicode`` map so ă, ș, ț extract exactly), with content written for the journey: the
DOCX states the one fact the assistant is asked about, so the cited answer can be checked
word for word; the other three are distinct, so a wrong citation is visible.

``python frontend/e2e/support/workspace_docs.py <out-dir>`` writes the four files and prints
one JSON object ``{name: {path, title, fact}}`` for the spec to read.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tests.fixtures.workspace.samples import (  # noqa: E402
    build_docx,
    build_pdf,
    build_xlsx,
    docx_paragraph,
    docx_table,
)

#: The sentence the assistant must quote (the fake model answers with source 1's first sentence).
DOCX_FACT = "Discountul maxim pentru clienții noi din Țara Bârsei este de 12% din valoarea comenzii."


def documents() -> dict[str, dict[str, object]]:
    docx = build_docx(
        docx_paragraph(DOCX_FACT)
        + docx_paragraph("Reducerea se aprobă de șeful echipei de vânzări și se notează în fișa clientului.")
        + docx_table([["Categorie client", "Discount"], ["Client nou", "12%"], ["Client fidel", "8%"]])
        + docx_paragraph("Politica intră în vigoare la 1 noiembrie 2026."))
    pdf = build_pdf([
        ["Comisionul agenților de vânzări este de 3% din încasările lunare.",
         "Plata comisionului se face până pe data de 15 a lunii următoare."],
        ["Obiectivul trimestrial al echipei este de 450.000 lei, verificat la ședința de vânzări."],
    ])
    xlsx = build_xlsx({
        "Încasări": [["Lună", "Județ", "Încasări (lei)"],
                     ["Iulie", "Sibiu", 41250],
                     ["August", "Constanța", 38900.5],
                     ["Septembrie", "Iași", 45120]],
    })
    csv = ("Client;Oraș;Persoană de contact;Observații\n"
           "Țesătoria Mureș;Târgu Mureș;Ștefan Ionescu;plată la 30 de zile\n"
           "Brutăria Ardeleană;Cluj-Napoca;Ioana Pătrașcu;livrare săptămânală\n").encode()
    return {
        "docx": {"file": "politica-discount-vanzari.docx", "data": docx,
                 "title": "politica-discount-vanzari", "fact": DOCX_FACT},
        "pdf": {"file": "regulament-comisioane.pdf", "data": pdf,
                "title": "regulament-comisioane", "fact": "Comisionul agenților de vânzări este de 3%"},
        "xlsx": {"file": "incasari-trimestrul-3.xlsx", "data": xlsx,
                 "title": "incasari-trimestrul-3", "fact": "Constanța"},
        "csv": {"file": "clienti-cheie.csv", "data": csv,
                "title": "clienti-cheie", "fact": "Țesătoria Mureș"},
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: workspace_docs.py <out-dir>", file=sys.stderr)
        return 2
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for key, doc in documents().items():
        path = out / str(doc["file"])
        path.write_bytes(doc["data"])  # type: ignore[arg-type]
        manifest[key] = {"path": str(path), "file": doc["file"], "title": doc["title"], "fact": doc["fact"]}
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
