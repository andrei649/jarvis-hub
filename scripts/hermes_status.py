#!/usr/bin/env python3
"""Reproducible code-equivalence status over the frozen 697-capability inventory.

The dated research ledger is immutable input, not a completion checklist.
Reviews are additive. Partial work, skips and changed evidence never count as done.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parent.parent
LEDGER = "docs/research/2026-09-07-hermes-absorption-ledger.json"
ASSESSMENT = "docs/hermes/assessment.json"
STATES = ("equivalent", "partial", "missing", "excluded", "needs_review")
LABELS = dict(zip(STATES, ("Echivalent", "Parțial", "Lipsă", "Exclus intenționat", "De reverificat"), strict=True))


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    """Bind UTF-8 source with universal newlines so Windows and Linux agree."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def load(root: Path = REPO) -> tuple[dict, dict]:
    return tuple(json.loads((root / path).read_text(encoding="utf-8"))
                 for path in (LEDGER, ASSESSMENT))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _evidence(root: Path, item: Any) -> tuple[str, bool]:
    _require(isinstance(item, dict) and set(item) == {"path", "sha256"}, "invalid evidence")
    name = item["path"]
    _require(_text(name) and "\\" not in name and ":" not in name
             and not PurePosixPath(name).is_absolute()
             and all(p not in {"", ".", ".."} for p in name.split("/")), "invalid evidence path")
    _require(isinstance(item["sha256"], str) and bool(re.fullmatch(r"[a-f0-9]{64}", item["sha256"])),
             "invalid evidence hash")
    path = (root / name).resolve()
    _require(path.is_relative_to(root.resolve()), "evidence path leaves repository")
    matches = path.is_file() and file_digest(path) == item["sha256"]
    return name, matches


def assess(ledger: dict, data: dict, root: Path = REPO) -> list[dict]:
    _require(isinstance(data, dict) and set(data) == {
        "schema_version", "inventory_count", "inventory_sha256", "base_sha", "assessed_at", "reviews",
    }, "invalid assessment schema")
    _require(type(data["schema_version"]) is int and data["schema_version"] == 1, "unsupported schema")
    caps = ledger.get("capabilities")
    _require(isinstance(caps, list) and type(data["inventory_count"]) is int
             and len(caps) == data["inventory_count"] and digest(ledger) == data["inventory_sha256"],
             "inventory changed: explicit identity migration and reassessment required")
    _require(isinstance(data["base_sha"], str) and bool(re.fullmatch(r"[a-f0-9]{40}", data["base_sha"])),
             "invalid inspected base")
    _require(isinstance(data["assessed_at"], str) and data["assessed_at"].endswith("Z"), "invalid timestamp")
    datetime.fromisoformat(data["assessed_at"].replace("Z", "+00:00"))
    _require(isinstance(data["reviews"], list), "reviews must be a list")
    rows = []
    for index, cap in enumerate(caps, 1):
        _require(isinstance(cap, dict) and _text(cap.get("name")) and _text(cap.get("cluster"))
                 and cap.get("decision") in {"keep", "skip", "copy", "update"}
                 and cap.get("nerva_state") in {"superior", "parity", "partial", "missing"}, "invalid inventory row")
        decision, old = cap["decision"], cap["nerva_state"]
        status = ("excluded" if decision == "skip" else
                  "equivalent" if decision == "keep" and old in {"parity", "superior"} else
                  "missing" if old == "missing" else "partial")
        rows.append({
            "id": f"H{index:03}", "name": cap["name"], "cluster": cap["cluster"].split(" (")[0],
            "decision": decision, "original_state": old, "status": status,
            "basis": "baseline_2026-09-07", "evidence": [],
            "summary": "Preluat din auditul 07.09; nereevaluat în această livrare.",
            "remaining": ("" if status in {"equivalent", "excluded"} else
                          "Reevaluare pe cod; cerințele și lipsurile sunt în rândul original."),
        })
    by_id = {row["id"]: row for row in rows}
    seen = set()
    fields = {"id", "row_sha256", "status", "summary", "remaining", "evidence"}
    for item in data["reviews"]:
        _require(isinstance(item, dict) and set(item) == fields, "invalid review fields")
        ident = item["id"]
        _require(isinstance(ident, str) and ident in by_id, "unknown review id")
        _require(ident not in seen, "duplicate review id")
        seen.add(ident)
        row = by_id[ident]
        _require(item["row_sha256"] == digest(caps[int(ident[1:]) - 1]), "review identity mismatch")
        _require(row["decision"] != "skip", "excluded scope cannot be silently changed")
        _require(item["status"] in {"equivalent", "partial", "missing"}
                 and _text(item["summary"]) and isinstance(item["remaining"], str), "invalid review status/text")
        _require((item["status"] == "equivalent") == (item["remaining"] == ""),
                 "equivalent cannot have remaining work; unfinished rows must name it")
        _require(isinstance(item["evidence"], list) and bool(item["evidence"]), "review needs evidence")
        checked = [_evidence(root, entry) for entry in item["evidence"]]
        names = [name for name, _ in checked]
        _require(len(set(names)) == len(names), "duplicate evidence")
        if item["status"] == "equivalent":
            code = any(name.startswith(("agents/", "frontend/src/", "mobile/src/", "desktop/"))
                       and "/test/" not in name for name in names)
            tests = any(name.startswith("tests/") or "/test/" in name for name in names)
            _require(code and tests, "equivalence needs source and tests")
        current = all(match for _, match in checked)
        row.update(status=item["status"] if current else "needs_review",
                   basis="reviewed" if current else "stale_evidence", evidence=item["evidence"],
                   summary=item["summary"], remaining=item["remaining"] if current else
                   "Dovada s-a schimbat sau lipsește; reevaluează înainte de a număra rândul ca terminat.")
    return rows


def metrics(rows: list[dict]) -> dict:
    counts = dict.fromkeys(STATES, 0)
    counts.update(Counter(row["status"] for row in rows))
    total = len(rows)
    accepted = total - counts["excluded"]
    return {
        "total": total, "accepted": accepted, "counts": counts,
        "all_percent": round(100 * counts["equivalent"] / total, 1) if total else 0.0,
        "accepted_percent": round(100 * counts["equivalent"] / accepted, 1) if accepted else 0.0,
        "reviewed": sum(row["basis"] == "reviewed" for row in rows),
        "reviewed_equivalent": sum(row["basis"] == "reviewed" and row["status"] == "equivalent" for row in rows),
        "inherited_equivalent": sum(row["basis"] == "baseline_2026-09-07" and row["status"] == "equivalent" for row in rows),
    }


def _md(value: str) -> str:
    value = " ".join(value.split())
    return re.sub(r"([\\`*\[\]|<>])", r"\\\1", value)


def reports(rows: list[dict], data: dict) -> dict[str, str]:
    result = metrics(rows)
    done = result["counts"]["equivalent"]
    out = [
        "# Sprint curent: echivalarea celor 697 de capabilități Hermes", "",
        f"**{done} / {result['total']} = {result['all_percent']}% echivalente complet în evaluarea documentată.**", "",
        f"Din acestea, **{result['reviewed_equivalent']}** au fost reevaluate pe cod în această livrare; "
        f"**{result['inherited_equivalent']}** păstrează verdictul auditului din 7 septembrie.", "",
        "**Acesta este un status inițial conservator, nu o reauditare completă a celor 697.** "
        "Verdictele moștenite și cele actualizate sunt vizibile pentru fiecare rând. "
        "Procentul de 88% discutat anterior privea altă listă și nu se aplică aici.", "",
        "[Toate cele 697 de rânduri](docs/HERMES_CAPABILITIES.md) · "
        "[Sprint, livrări și următorii pași](docs/HERMES_SPRINT.md) · "
        "[Planul tehnic](docs/HERMES_ABSORPTION.md)", "",
        "| Stare cod | Rânduri | Din 697 |", "|---|---:|---:|",
    ]
    for state in STATES:
        count = result["counts"][state]
        out.append(f"| {LABELS[state]} | {count} | {100 * count / result['total']:.1f}% |")
    out.extend([
        "", f"**Ținta acceptată în produs:** {result['accepted']} rânduri; progres "
        f"{done}/{result['accepted']} = **{result['accepted_percent']}%**. "
        "Cele 107 excluderi rămân vizibile, nu sunt numărate ca implementări.", "",
        f"**Acoperirea reevaluării curente:** {result['reviewed']}/{result['total']} rânduri. "
        "Restul păstrează auditul inițial. Existența unui fișier sau a unui PR nu închide automat un rând.", "",
        "**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. "
        "Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. "
        "Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. "
        "Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.", "",
        "## Pe domenii", "", "| Domeniu | Total | Echiv. | Parțial | Lipsă | Exclus | Reverificare |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for cluster in dict.fromkeys(row["cluster"] for row in rows):
        group = [row for row in rows if row["cluster"] == cluster]
        counts = metrics(group)["counts"]
        out.append(f"| {_md(cluster)} | {len(group)} | " + " | ".join(str(counts[s]) for s in STATES) + " |")
    out.extend([
        "", "## Actualizare", "",
        f"Evaluare: `{data['assessed_at']}`. Cod inspectat: `{data['base_sha']}`. "
        f"Inventar înghețat: SHA-256 `{data['inventory_sha256']}`.", "",
        "Sursa editabilă este [assessment.json](docs/hermes/assessment.json). "
        "Actualizează numai rândurile inspectate, cu motiv, lipsuri și hash-uri ale codului/testelor. "
        "Dacă dovezile se schimbă sau dispar, rândul trece automat la «De reverificat» și pierde creditul de finalizare. "
        "Data reauditării moștenite nu este rescrisă.", "",
        "```text", "python scripts/hermes_status.py summary", "python scripts/hermes_status.py list --state partial --limit 20",
        "python scripts/hermes_status.py show H515", "python scripts/hermes_status.py write",
        "python scripts/hermes_status.py check", "```", "",
        "Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, "
        "identitatea tuturor celor 697 de rânduri și lipsa derivării unor procente din PR-uri sau din bifele HA.", "",
    ])
    detail = ["# Cele 697 de capabilități Hermes — status cod", "",
              "[Statusul sprintului](../HERMES_STATUS.md) · [Reguli și livrări](HERMES_SPRINT.md)", "",
              "ID-urile H001–H697 sunt poziții în inventarul înghețat, validate prin hash. "
              "Folosește căutarea paginii pentru nume/ID sau comanda `show` pentru cerința originală completă. "
              "«Audit 07.09» înseamnă moștenit, nu verificat din nou. Dovezile legate sunt fișiere inspectate; "
              "simpla lor existență nu dovedește întregul flux și nu afirmă că testele au fost rulate în această livrare.", ""]
    for cluster in dict.fromkeys(row["cluster"] for row in rows):
        detail.extend([f"## {_md(cluster)}", "", "| ID | Capabilitate | Decizie inițială | Stare cod | Bază | Observație / restanță |",
                       "|---|---|---|---|---|---|"])
        for row in (r for r in rows if r["cluster"] == cluster):
            basis = "Audit 07.09" if row["basis"] == "baseline_2026-09-07" else "Reevaluat" if row["basis"] == "reviewed" else "Dovadă schimbată"
            note = row["remaining"] or row["summary"]
            links = " ".join(f"[d{i + 1}](../{e['path']})" for i, e in enumerate(row["evidence"][:3]))
            detail.append(f"| <a id=\"{row['id'].lower()}\"></a>{row['id']} | {_md(row['name'])} | {row['decision']} | "
                          f"{LABELS[row['status']]} | {basis} | {_md(note)} {links} |")
        detail.append("")
    return {"HERMES_STATUS.md": "\n".join(out), "docs/HERMES_CAPABILITIES.md": "\n".join(detail)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    summary = subs.add_parser("summary")
    summary.add_argument("--json", action="store_true")
    listing = subs.add_parser("list")
    listing.add_argument("--state", choices=STATES)
    listing.add_argument("--cluster")
    listing.add_argument("--limit", type=int, default=20)
    show = subs.add_parser("show")
    show.add_argument("id")
    subs.add_parser("write")
    subs.add_parser("check")
    ns = parser.parse_args(argv)
    try:
        ledger, data = load()
        rows = assess(ledger, data)
        if ns.command == "summary":
            result = metrics(rows)
            if ns.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"{result['counts']['equivalent']}/{result['total']} = {result['all_percent']}% documented code equivalence")
                print(f"Accepted scope: {result['accepted']}; current reviews: {result['reviewed']}; inherited equivalent: {result['inherited_equivalent']}")
                print(json.dumps(result["counts"], ensure_ascii=False))
        elif ns.command == "list":
            _require(0 < ns.limit <= 697, "limit must be 1..697")
            selected = [r for r in rows if (not ns.state or r["status"] == ns.state)
                        and (not ns.cluster or ns.cluster.lower() in r["cluster"].lower())]
            for row in selected[:ns.limit]:
                print(f"{row['id']} {row['status']:<12} {row['name'][:100]}")
            print(f"{min(ns.limit, len(selected))} of {len(selected)} rows")
        elif ns.command == "show":
            row = next((r for r in rows if r["id"] == ns.id.upper()), None)
            if row is None:
                print(f"not found: {ns.id}", file=sys.stderr)
                return 1
            print(json.dumps({"assessment": row, "original": ledger["capabilities"][int(row["id"][1:]) - 1]},
                             ensure_ascii=False, indent=2))
        else:
            drift = []
            for name, content in reports(rows, data).items():
                path = REPO / name
                if ns.command == "write":
                    path.write_text(content, encoding="utf-8", newline="\n")
                elif not path.is_file() or path.read_text(encoding="utf-8") != content:
                    drift.append(name)
            if drift:
                print("stale reports: " + ", ".join(drift), file=sys.stderr)
                return 1
            print("Hermes 697 reports " + ("written" if ns.command == "write" else "in sync"))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Hermes status error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
