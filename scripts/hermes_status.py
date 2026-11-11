#!/usr/bin/env python3
"""Reproducible code-equivalence status over the frozen 697-capability inventory.

The dated research ledger is immutable input, not a completion checklist.
Reviews are additive. Partial work, skips and failing acceptance suites never count as done.

Evidence model (owner decision 2026-11-10, docs/decisions/2026-11-10-hermes-integration-by-feature.md §3):
every row belongs to exactly one feature area (docs/hermes/areas.json), and each area owns an
acceptance suite of pytest files or node ids. A row's status is a reviewed judgement; what keeps
an `equivalent` row honest is its area's suite passing, not a hash of the files it cites. A
failing suite demotes that area's equivalent rows to `needs_review` (basis `suite_failed`);
moving or editing code changes no row. Citations (`path:line`) in summaries are prose pointers.

  summary | list | show ID     read the records; `show --recorded` adds the stored review
  write | check               regenerate / compare HERMES_STATUS.md and docs/HERMES_CAPABILITIES.md;
                              check also validates the area map and that every suite entry resolves
  verify [--junit FILE]       read a pytest JUnit result (CI reuses its own run) or run the suites
                              here, then name the areas that failed and the rows that lose credit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess  # nosec B404  # fixed pytest argv only, never a shell
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from defusedxml.ElementTree import fromstring as parse_xml

REPO = Path(__file__).resolve().parent.parent
LEDGER = "docs/research/2026-09-07-hermes-absorption-ledger.json"
ASSESSMENT = "docs/hermes/assessment.json"
AREAS = "docs/hermes/areas.json"
SCHEMA_VERSION = 3
STATES = ("equivalent", "partial", "missing", "excluded", "needs_review")
LABELS = dict(zip(STATES, ("Echivalent", "Parțial", "Lipsă", "Exclus intenționat", "De reverificat"), strict=True))
LANES = ("own", "adopt", "run")
ORIGINS = ("seeded", "owner")
# A suite is thin when it is this small, or when fewer than this share of the area's reviewed
# rows cite one of its files: it then proves less than the area's verdicts claim.
THIN_FILES = 5
THIN_COVERAGE = 0.6
SUITE_ENTRY = re.compile(r"tests/(?:[A-Za-z0-9_]+/)*test_[A-Za-z0-9_]+\.py(?:::[A-Za-z_][A-Za-z0-9_]*){0,2}")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def load(root: Path = REPO) -> tuple[dict, dict, dict]:
    return tuple(json.loads((root / path).read_text(encoding="utf-8"))
                 for path in (LEDGER, ASSESSMENT, AREAS))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _evidence_path(name: Any) -> str:
    """A repository-relative pointer. It is not pinned: a moved file changes no verdict."""
    _require(_text(name) and "\\" not in name and ":" not in name
             and not PurePosixPath(name).is_absolute()
             and all(p not in {"", ".", ".."} for p in name.split("/")), "invalid evidence path")
    return name


def suite_file(entry: str) -> str:
    return entry.split("::", 1)[0]


def _resolve_entry(root: Path, area: str, entry: Any) -> str:
    """A suite entry must name a test file that exists, and any node in it must be defined there."""
    _require(isinstance(entry, str) and bool(SUITE_ENTRY.fullmatch(entry)),
             f"area {area}: invalid suite entry {entry!r}")
    path = root / suite_file(entry)
    _require(path.is_file(), f"area {area}: suite entry {entry} names no test file; update {AREAS}")
    names = entry.split("::")[1:]
    if names:
        source = path.read_text(encoding="utf-8")
        for name in names:
            _require(bool(re.search(rf"^[ \t]*(?:async[ \t]+def|def|class)[ \t]+{name}\b", source, re.M)),
                     f"area {area}: suite entry {entry} names nothing defined in that file")
    return entry


def areas_by_row(areas: dict, row_ids: list[str], root: Path = REPO) -> tuple[list[dict], dict[str, str]]:
    """Validate the area map: every inventory row in exactly one area, every suite entry real."""
    _require(isinstance(areas, dict) and set(areas) == {"schema_version", "decision", "areas"}
             and areas["schema_version"] == 1 and isinstance(areas["areas"], list) and areas["areas"],
             "invalid area map schema")
    known = set(row_ids)
    owner: dict[str, str] = {}
    seen: set[str] = set()
    for area in areas["areas"]:
        _require(isinstance(area, dict) and set(area) == {"id", "title", "lanes", "suite_origin", "rows", "suite"},
                 "invalid area fields")
        ident = area["id"]
        _require(isinstance(ident, str) and bool(re.fullmatch(r"[a-z][a-z0-9-]*", ident)), "invalid area id")
        _require(ident not in seen, f"duplicate area {ident}")
        seen.add(ident)
        _require(_text(area["title"]), f"area {ident}: title required")
        lanes = area["lanes"]
        _require(isinstance(lanes, list) and bool(lanes) and len(set(lanes)) == len(lanes)
                 and set(lanes) <= set(LANES), f"area {ident}: lanes must be a subset of {LANES}")
        _require(area["suite_origin"] in ORIGINS, f"area {ident}: suite_origin must be one of {ORIGINS}")
        _require(isinstance(area["rows"], list) and bool(area["rows"]), f"area {ident}: rows required")
        for row in area["rows"]:
            _require(row in known, f"area {ident}: unknown row {row!r}")
            _require(row not in owner, f"row {row} is mapped to both {owner.get(row)} and {ident}")
            owner[row] = ident
        suite = area["suite"]
        _require(isinstance(suite, list), f"area {ident}: suite must be a list")
        _require(len(set(suite)) == len(suite), f"area {ident}: duplicate suite entry")
        for entry in suite:
            _resolve_entry(root, ident, entry)
    unmapped = [row for row in row_ids if row not in owner]
    _require(not unmapped, f"rows mapped to no area: {', '.join(unmapped[:10])}"
                           + (f" (+{len(unmapped) - 10})" if len(unmapped) > 10 else ""))
    return areas["areas"], owner


def assess(ledger: dict, data: dict, areas: dict, root: Path = REPO,
           results: dict[str, dict] | None = None) -> list[dict]:
    """Derive every row's status. `results` maps area id -> suite_results() entry, when known."""
    _require(isinstance(data, dict), "invalid assessment schema")
    _require(data.get("schema_version") == SCHEMA_VERSION, "unsupported schema")
    fields = {
        "schema_version", "inventory_count", "inventory_sha256", "base_sha", "assessed_at", "reviews",
        "scope_reopenings",
    }
    _require(set(data) == fields, "invalid assessment schema")
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
    area_list, owner = areas_by_row(areas, list(by_id), root)
    for row in rows:
        row["area"] = owner[row["id"]]
    reopenings = data["scope_reopenings"]
    _require(isinstance(reopenings, list), "scope reopenings must be a list")
    reopened = set()
    for item in reopenings:
        _require(isinstance(item, dict) and set(item) == {
            "id", "row_sha256", "decided_at", "reason",
        }, "invalid scope reopening fields")
        ident = item["id"]
        _require(isinstance(ident, str) and ident in by_id, "unknown scope reopening id")
        _require(ident not in reopened, "duplicate scope reopening")
        row = by_id[ident]
        _require(row["decision"] == "skip", "only originally excluded rows can be reopened")
        _require(item["row_sha256"] == digest(caps[int(ident[1:]) - 1]),
                 "scope reopening identity mismatch")
        stamp = item["decided_at"]
        _require(_text(stamp) and "T" in stamp and stamp.endswith("Z"),
                 "invalid scope reopening timestamp")
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        _require(_text(item["reason"]), "scope reopening needs a reason")
        reopened.add(ident)
        row.update(status="needs_review", basis="scope_reopened",
                   summary=item["reason"],
                   remaining="Readmis în obiectivul de paritate completă; necesită evaluare pe cod și teste. "
                             "Vechiul verdict de excludere nu dovedește implementarea.")
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
        _require(row["decision"] != "skip" or ident in reopened,
                 "excluded scope cannot be silently changed")
        _require(item["status"] in {"equivalent", "partial", "missing"}
                 and _text(item["summary"]) and isinstance(item["remaining"], str), "invalid review status/text")
        _require((item["status"] == "equivalent") == (item["remaining"] == ""),
                 "equivalent cannot have remaining work; unfinished rows must name it")
        _require(isinstance(item["evidence"], list) and bool(item["evidence"]), "review needs evidence")
        names = [_evidence_path(entry) for entry in item["evidence"]]
        _require(len(set(names)) == len(names), "duplicate evidence")
        if item["status"] == "equivalent":
            code = any(name.startswith(("agents/", "frontend/src/", "mobile/src/", "desktop/"))
                       and "/test/" not in name for name in names)
            tests = any(name.startswith("tests/") or "/test/" in name for name in names)
            _require(code and tests, "equivalence needs source and tests")
        row.update(status=item["status"], basis="reviewed", evidence=names,
                   summary=item["summary"], remaining=item["remaining"])
    for area in area_list:
        equivalent = [by_id[r] for r in area["rows"] if by_id[r]["status"] == "equivalent"]
        _require(not equivalent or bool(area["suite"]),
                 f"area {area['id']}: equivalent rows need an acceptance suite")
        outcome = (results or {}).get(area["id"])
        if outcome is None or outcome["state"] == "passed":
            continue
        for row in equivalent:
            row.update(status="needs_review", basis="suite_failed",
                       remaining=f"Suita de acceptanță a domeniului «{area['id']}» nu a trecut "
                                 f"({outcome['reason']}); reverifică rândul înainte de a-l număra ca terminat.")
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


# --- acceptance suites ------------------------------------------------------------------------

def _module(entry: str) -> tuple[str, list[str]]:
    """`tests/a/test_x.py::TestK::test_y` -> ("tests.a.test_x", ["TestK", "test_y"])."""
    parts = entry.split("::")
    return parts[0][:-3].replace("/", "."), parts[1:]


def _matches(entry: str, classname: str, name: str) -> bool:
    module, nodes = _module(entry)
    if classname == "" and name == module:   # a collection error or a module-level skip
        return True
    if not nodes:
        return classname == module or classname.startswith(module + ".")
    *classes, last = nodes
    if classname == ".".join([module, *classes]) and (name == last or name.startswith(last + "[")):
        return True   # a test function, or a method of the named class
    return classname == ".".join([module, *nodes])   # the entry names a class: all its methods


def read_junit(text: str) -> list[tuple[str, str, str]]:
    """Each testcase of a pytest JUnit file as (classname, name, outcome)."""
    root = parse_xml(text.encode("utf-8") if isinstance(text, str) else text)
    cases = []
    for case in root.iter("testcase"):
        tags = {child.tag for child in case}
        outcome = ("failed" if tags & {"failure", "error"} else
                   "skipped" if "skipped" in tags else "passed")
        cases.append((case.get("classname", ""), case.get("name", ""), outcome))
    _require(bool(cases), "JUnit result holds no testcase")
    return cases


def suite_results(areas: list[dict], cases: list[tuple[str, str, str]],
                  only: set[str] | None = None) -> dict[str, dict]:
    """Judge each area's suite against one test run.

    A suite passes only when every entry ran, nothing in it failed or errored, and at least one
    of its tests passed. An entry the run never reached counts against the suite: a full CI run
    collects every test file, so a missing entry means the suite rotted or collection broke.
    """
    by_module: dict[str, list[tuple[str, str, str]]] = {}
    for case in cases:
        key = case[0] or case[1]
        top = ".".join(key.split(".")[:2]) if key.startswith("tests.") else key
        by_module.setdefault(top, []).append(case)
    out = {}
    for area in areas:
        if only is not None and area["id"] not in only:
            continue
        passed = skipped = 0
        failed, missing = [], []
        for entry in area["suite"]:
            module = _module(entry)[0]
            pool = [c for key, group in by_module.items()
                    if module == key or module.startswith(key + ".") for c in group]
            hits = [c for c in pool if _matches(entry, c[0], c[1])]
            if not hits:
                missing.append(entry)
                continue
            for classname, name, outcome in hits:
                if outcome == "failed":
                    failed.append(f"{classname}::{name}" if classname else name)
                elif outcome == "skipped":
                    skipped += 1
                else:
                    passed += 1
        if failed:
            state, reason = "failed", f"{len(failed)} test(e) picate, ex. {failed[0]}"
        elif missing:
            state, reason = "failed", f"{len(missing)} intrări nerulate, ex. {missing[0]}"
        elif not passed:
            state, reason = "failed", "niciun test nu a trecut (toate omise sau suită goală)"
        else:
            state, reason = "passed", ""
        out[area["id"]] = {"state": state, "reason": reason, "passed": passed, "skipped": skipped,
                           "failed": failed, "missing": missing}
    return out


def run_suites(areas: list[dict], only: set[str] | None = None, root: Path = REPO) -> str:
    """Run the selected suites once with pytest here and return the JUnit text."""
    entries = sorted({e for a in areas if only is None or a["id"] in only for e in a["suite"]})
    _require(bool(entries), "no suite entries selected")
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "hermes-suites.xml"
        argv = [sys.executable, "-m", "pytest", *entries, "-q", "-p", "no:cacheprovider",
                f"--junitxml={junit}"]
        subprocess.run(argv, cwd=root, check=False,  # noqa: S603  # nosec B603  # fixed argv, no shell
                       env={**os.environ, "JARVIS_TESTING": "1"})
        _require(junit.is_file(), "pytest wrote no JUnit result")
        return junit.read_text(encoding="utf-8")


def board(rows: list[dict], areas: list[dict], results: dict[str, dict] | None = None) -> list[dict]:
    """The per-area scoreboard: lane, row counts, suite size and suite state."""
    by_area: dict[str, list[dict]] = {}
    for row in rows:
        by_area.setdefault(row["area"], []).append(row)
    out = []
    for area in areas:
        group = by_area.get(area["id"], [])
        files = {suite_file(entry) for entry in area["suite"]}
        reviewed = [r for r in group if r["basis"] in {"reviewed", "suite_failed"}]
        covered = sum(any(path in files for path in r["evidence"]) for r in reviewed)
        thin = len(files) < THIN_FILES or (bool(reviewed) and covered / len(reviewed) < THIN_COVERAGE)
        live = (results or {}).get(area["id"])
        out.append({
            "id": area["id"], "title": area["title"], "lanes": area["lanes"], "rows": len(group),
            "counts": metrics(group)["counts"], "suite": len(area["suite"]), "origin": area["suite_origin"],
            "covered": covered, "reviewed": len(reviewed), "thin": thin,
            "state": live["state"] if live else None,
        })
    return out


# --- reports ----------------------------------------------------------------------------------

def _md(value: str) -> str:
    value = " ".join(value.split())
    return re.sub(r"([\\`*\[\]|<>])", r"\\\1", value)


def _suite_state(item: dict) -> str:
    origin = "seed din dovezi" if item["origin"] == "seeded" else "scrisă de owner"
    state = f"**subțire**, {origin}" if item["thin"] else origin
    if item["state"]:
        state += f"; {'trece' if item['state'] == 'passed' else '**picată**'}"
    return state


def scoreboard_lines(items: list[dict]) -> list[str]:
    out = ["| Domeniu | Lane | Rânduri | Echiv. | Parțial | Lipsă | Exclus | Reverificare | Suită | Stare suită |",
           "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for item in items:
        counts = item["counts"]
        out.append(f"| [{item['id']}](docs/HERMES_CAPABILITIES.md#area-{item['id']}) — {_md(item['title'])} | "
                   f"{'/'.join(item['lanes'])} | {item['rows']} | "
                   + " | ".join(str(counts[s]) for s in STATES)
                   + f" | {item['suite']} | {_suite_state(item)} |")
    return out


def reports(rows: list[dict], data: dict, areas: dict) -> dict[str, str]:
    result = metrics(rows)
    area_list = areas["areas"]
    items = board(rows, area_list)
    done = result["counts"]["equivalent"]
    thin = [item["id"] for item in items if item["thin"]]
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
        f"Excluderi active: {result['counts']['excluded']}. "
        f"Readmise explicit din vechiul audit: {len(data['scope_reopenings'])}; "
        "readmiterea nu acordă credit de implementare.", "",
        f"**Acoperirea reevaluării curente:** {result['reviewed']}/{result['total']} rânduri. "
        "Restul păstrează auditul inițial sau așteaptă evaluarea după readmitere. "
        "Existența unui fișier sau a unui PR nu închide automat un rând.", "",
        "**Regulă de calcul:** fiecare rând are greutate egală; parțial = zero credit de finalizare. "
        "Un rând compus rămâne parțial cât timp are cerințe acceptate neimplementate. "
        "Un `update` rămâne parțial chiar dacă vechiul audit îl numea superior/parity, până când lipsurile sunt reconciliate. "
        "Acest procent măsoară codul documentat, nu efortul rămas, calitatea UX sau probele pe servicii reale.", "",
        "## Pe domenii de funcționalitate", "",
        f"Fiecare rând aparține unui singur domeniu din [areas.json](docs/hermes/areas.json) "
        f"({len(area_list)} domenii). Lane: own = cod Nerva nativ, adopt = cod Hermes preluat, "
        "run = sidecar-ul Hermes guvernat. Suita de acceptanță a domeniului ține rândurile echivalente "
        "oneste: dacă pică, rândurile echivalente ale domeniului trec la «De reverificat». "
        "CI o evaluează la fiecare rulare din rezultatul JUnit al suitei pytest normale "
        "(`hermes_status.py verify --junit`), fără a rula testele a doua oară. "
        f"«Subțire» = sub {THIN_FILES} fișiere sau sub {int(THIN_COVERAGE * 100)}% din rândurile reevaluate "
        "ale domeniului citează un test din suită; suitele de azi sunt semănate din testele deja citate "
        "în dovezi și urmează să fie înlocuite cu suite scrise din perspectiva owner-ului.", "",
        *scoreboard_lines(items), "",
        f"Suite subțiri: {', '.join(thin) if thin else 'niciuna'}.", "",
        "## Actualizare", "",
        f"Evaluare: `{data['assessed_at']}`. Cod inspectat: `{data['base_sha']}`. "
        f"Inventar înghețat: SHA-256 `{data['inventory_sha256']}`.", "",
        "Sursa editabilă este [assessment.json](docs/hermes/assessment.json): verdict, motiv, lipsuri și "
        "căile dovezilor (fără hash-uri). Un merge care doar mută sau editează cod nu schimbă niciun rând; "
        "un rând se schimbă când cineva îl reevaluează sau când suita domeniului său pică. "
        "Citările `cale:linie` din texte sunt indicatoare în proză, nu sunt fixate. "
        "Data reauditării moștenite nu este rescrisă.", "",
        "```text", "python scripts/hermes_status.py summary", "python scripts/hermes_status.py list --state partial --limit 20",
        "python scripts/hermes_status.py show H515", "python scripts/hermes_status.py write",
        "python scripts/hermes_status.py check", "python scripts/hermes_status.py verify --area mcp",
        "python scripts/hermes_status.py verify --junit pytest-junit.xml", "```", "",
        "Pagina și inventarul afișat sunt generate din aceleași date; testele verifică derivarea, "
        "identitatea tuturor celor 697 de rânduri, harta domeniilor și lipsa derivării unor procente din PR-uri sau din bifele HA.", "",
    ])
    detail = ["# Cele 697 de capabilități Hermes — status cod", "",
              "[Statusul sprintului](../HERMES_STATUS.md) · [Reguli și livrări](HERMES_SPRINT.md)", "",
              "ID-urile H001–H697 sunt poziții în inventarul înghețat, validate prin hash. "
              "Rândurile sunt grupate pe domeniile de funcționalitate din `docs/hermes/areas.json`. "
              "Folosește căutarea paginii pentru nume/ID sau comanda `show` pentru cerința originală completă. "
              "«Audit 07.09» înseamnă moștenit, nu verificat din nou. Dovezile legate sunt fișiere citate la "
              "reevaluare; nu sunt fixate prin hash, iar ce ține un rând echivalent onest este suita de "
              "acceptanță a domeniului său.", "",
              *[line.replace("(docs/HERMES_CAPABILITIES.md#", "(#") for line in scoreboard_lines(items)], ""]
    by_area: dict[str, list[dict]] = {}
    for row in rows:
        by_area.setdefault(row["area"], []).append(row)
    for area, item in zip(area_list, items, strict=True):
        detail.extend([f"<a id=\"area-{area['id']}\"></a>", "",
                       f"## {_md(area['id'])} — {_md(area['title'])}", "",
                       f"Lane: {'/'.join(area['lanes'])}. Suită: {item['suite']} intrări ({_suite_state(item)}); "
                       f"{item['covered']}/{item['reviewed']} rânduri reevaluate citează un test din suită.", "",
                       "| ID | Capabilitate | Decizie inițială | Stare cod | Bază | Observație / restanță |",
                       "|---|---|---|---|---|---|"])
        for row in by_area.get(area["id"], []):
            basis = {"baseline_2026-09-07": "Audit 07.09", "reviewed": "Reevaluat",
                     "scope_reopened": "Readmis; neevaluat", "suite_failed": "Suită picată"}[row["basis"]]
            note = row["remaining"] or row["summary"]
            links = " ".join(f"[d{i + 1}](../{path})" for i, path in enumerate(row["evidence"][:3]))
            detail.append(f"| <a id=\"{row['id'].lower()}\"></a>{row['id']} | {_md(row['name'])} | {row['decision']} | "
                          f"{LABELS[row['status']]} | {basis} | {_md(note)} {links} |")
        detail.append("")
    return {"HERMES_STATUS.md": "\n".join(out), "docs/HERMES_CAPABILITIES.md": "\n".join(detail)}


def _verify(ns: argparse.Namespace, ledger: dict, data: dict, areas: dict) -> int:
    rows = assess(ledger, data, areas)   # validates the map before anything runs
    area_list = areas["areas"]
    known = {a["id"] for a in area_list}
    only = set(ns.area) if ns.area else None
    _require(only is None or only <= known, f"unknown area: {', '.join(sorted((only or set()) - known))}")
    text = (Path(ns.junit).read_text(encoding="utf-8", errors="replace") if ns.junit
            else run_suites(area_list, only))
    results = suite_results(area_list, read_junit(text), only)
    rows = assess(ledger, data, areas, results=results)
    for item in board(rows, area_list, results):
        if item["state"] is None:
            continue
        outcome = results[item["id"]]
        mark = "PASS" if item["state"] == "passed" else "FAIL"
        print(f"{mark} {item['id']:<15} {outcome['passed']} passed, {outcome['skipped']} skipped"
              + (f" — {outcome['reason']}" if outcome["reason"] else ""))
    flipped = [r for r in rows if r["basis"] == "suite_failed"]
    if flipped:
        print("rows losing equivalent credit until re-reviewed: "
              + " ".join(f"{r['id']}({r['area']})" for r in flipped))
    failed = [i for i, o in results.items() if o["state"] != "passed"]
    print(f"{len(results) - len(failed)}/{len(results)} area suites pass")
    return 1 if failed else 0


def show_payload(ledger: dict, data: dict, areas: dict, row: dict, *, recorded: bool = False) -> dict:
    """One current row, its area and the frozen capability; with ``recorded``, also the stored
    review (or None). The stored review is history: it never replaces the current assessment,
    whose status a failing area suite may have demoted."""
    area = next(a for a in areas["areas"] if a["id"] == row["area"])
    payload = {"assessment": row, "area": {k: area[k] for k in ("id", "title", "lanes", "suite")},
               "original": ledger["capabilities"][int(row["id"][1:]) - 1]}
    if recorded:
        payload["recorded_review"] = next((item for item in data["reviews"] if item["id"] == row["id"]), None)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="command", required=True)
    summary = subs.add_parser("summary")
    summary.add_argument("--json", action="store_true")
    listing = subs.add_parser("list")
    listing.add_argument("--state", choices=STATES)
    listing.add_argument("--cluster")
    listing.add_argument("--area")
    listing.add_argument("--limit", type=int, default=20)
    show = subs.add_parser("show")
    show.add_argument("id")
    show.add_argument("--recorded", action="store_true",
                      help="also show the stored review; the current assessment is unchanged")
    subs.add_parser("write")
    subs.add_parser("check")
    verify = subs.add_parser("verify", help="judge the area acceptance suites")
    verify.add_argument("--junit", help="read this pytest JUnit result instead of running the suites")
    verify.add_argument("--area", action="append", help="only this area (repeatable)")
    ns = parser.parse_args(argv)
    try:
        ledger, data, areas = load()
        if ns.command == "verify":
            return _verify(ns, ledger, data, areas)
        rows = assess(ledger, data, areas)
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
                        and (not ns.cluster or ns.cluster.lower() in r["cluster"].lower())
                        and (not ns.area or ns.area == r["area"])]
            for row in selected[:ns.limit]:
                print(f"{row['id']} {row['status']:<12} {row['name'][:100]}")
            print(f"{min(ns.limit, len(selected))} of {len(selected)} rows")
        elif ns.command == "show":
            row = next((r for r in rows if r["id"] == ns.id.upper()), None)
            if row is None:
                print(f"not found: {ns.id}", file=sys.stderr)
                return 1
            print(json.dumps(show_payload(ledger, data, areas, row, recorded=ns.recorded),
                             ensure_ascii=False, indent=2))
        else:
            drift = []
            for name, content in reports(rows, data, areas).items():
                path = REPO / name
                if ns.command == "write":
                    path.write_text(content, encoding="utf-8", newline="\n")
                elif not path.is_file() or path.read_text(encoding="utf-8") != content:
                    drift.append(name)
            if drift:
                print("stale reports: " + ", ".join(drift), file=sys.stderr)
                return 1
            print("Hermes 697 reports " + ("written" if ns.command == "write" else "in sync")
                  + f"; {len(areas['areas'])} areas map every row once and every suite entry resolves")
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Hermes status error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
