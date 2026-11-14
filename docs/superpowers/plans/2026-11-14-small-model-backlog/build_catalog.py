"""Build planning-only coverage from the existing canonical parsers; never edit verdicts."""

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
import re
import sys

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[3]
BASE = '587977b623cf2d1099733d57037e1c056babe1e5'
INPUTS = ['BACKLOG.md', 'docs/hermes/assessment.json', 'docs/hermes/areas.json',
          'docs/research/2026-09-07-hermes-absorption-ledger.json']
# Review flags are planning overlays, never changes to the assessment ledger.
REVIEW = {
    'H040': 'State is not reloaded by the default constructor; discovery roots and conflict/replay semantics need repair.',
    'H032': 'Early-quorum/timeout claims need alignment with gather and unbounded model loading.',
    'H657': 'Manual promotion does not fence a partitioned old owner automatically; state the guarantee precisely.',
    'H214': 'Web/procedural companion does not prove native desktop or VLM generation acceptance.',
    'H238': 'Backend labels and reference palette extraction overstate the procedural implementation.',
    'H590': 'Pet generation and runtime journey need composed acceptance, not only fake-fetch tests.',
    'H690': 'Actual macOS TCC permission continuity across upgrades remains an external acceptance gate.',
    'H429': 'Streaming scrubber change breaks legacy callback semantics in CI.',
    'H508': 'Safe-mode/scanner contract failures require security review before claiming equivalence.',
}


def write(name, value):
    path = PACKAGE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def file_hash(path):
    p = ROOT / path
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import backlog
    import hermes_status

    ledger, assessment, areas = hermes_status.load(ROOT)
    rows = hermes_status.assess(ledger, assessment, areas, ROOT)
    assert len(rows) == 697
    groups = defaultdict(list)
    all_paths = set(INPUTS)
    index = []
    for row in rows:
        ident = row['id']
        original = ledger['capabilities'][int(ident[1:]) - 1]
        evidence = row['evidence']
        all_paths.update(evidence)
        prior_specs = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'docs/hermes').glob(ident.lower() + '-*.md'))
        residual = row['remaining']
        # Keep original wording, including historical limitations. Do not invent contract detail.
        requirements = [x.strip() for x in re.split(r'\n\s*\n', residual) if x.strip()]
        work = row['status'] != 'equivalent' or ident in REVIEW
        card = {
            'id': ident, 'title': row['name'], 'area': row['area'],
            'recorded_status': row['status'], 'planning_status': 'needs_design' if work else 'retain_and_verify',
            'spec_state': 'needs_design' if work else 'evidence_only',
            'source_sha': BASE, 'source_row_sha256': hermes_status.digest(original),
            'contract': original['hermes'], 'governance': original['governance'],
            'remaining_verbatim': residual, 'requirement_sections': requirements,
            'review_overlay': REVIEW.get(ident),
            'original_dependency_note': original.get('depends_on', ''),
            'historical_exclusion_reason': original.get('rationale') if row['status'] == 'excluded' else None,
            'source_files': [p for p in evidence if not p.startswith('tests/') and '/test/' not in p],
            'existing_test_files': [p for p in evidence if p.startswith('tests/') or '/test/' in p],
            'prior_specs_to_revalidate': prior_specs,
            'source_refs': ['docs/hermes/assessment.json#' + ident,
                            'docs/research/2026-09-07-hermes-absorption-ledger.json#' + ident],
            'next_action': ('Select ONE residual requirement, inspect its actual caller and cited test, and produce a reviewed packet using PACKET-TEMPLATE.md. Check related ready packets first; no whole-contract implementation assignment.' if work else
                            'Preserve existing behavior. Reevaluate if an affected area suite fails; do not treat this recorded status as fresh certification.'),
            'completion_contract': 'All accepted clauses, real caller, refusal/recovery behavior and applicable platform evidence; mocks alone do not certify live acceptance. Never shrink the 697-row inventory.',
        }
        groups[row['area']].append(card)
        index.append({k: card[k] for k in ['id', 'title', 'area', 'recorded_status', 'planning_status']})
    for area, cards in groups.items():
        write('catalog/contracts/' + area + '.json', cards)

    text = (ROOT / 'BACKLOG.md').read_text()
    source_lines = text.splitlines()
    checkbox = backlog.parse(ROOT / 'BACKLOG.md')
    tables, diagnostics, excluded = backlog._parse_table_work_items(text)
    cards = []
    for row in checkbox:
        if row.done:
            continue
        cards.append({'id': 'BL-CB-' + row.label, 'source_id': row.label,
                      'kind': 'checkbox', 'line': row.line, 'section': row.section,
                      'title': row.summary, 'requirement_verbatim': '\n'.join([row.text, *row.body]),
                      'planning_status': 'needs_design', 'source_sha': BASE})
    for row in tables:
        if row.status not in {'open', 'blocked'}:
            continue
        cards.append({'id': f'BL-TB-{row.ident}-L{row.line}', 'source_id': row.ident,
                      'kind': 'table', 'line': row.line, 'section': row.section,
                      'title': row.summary, 'requirement_verbatim': source_lines[row.line - 1],
                      'planning_status': 'needs_design', 'source_sha': BASE})
    for card in cards:
        card['source_ref'] = f"BACKLOG.md:{card['line']}"
        card['hermes_mentions'] = sorted(set(re.findall(r'\bH\d{3}\b', card['requirement_verbatim'])))
        card['next_action'] = 'Read the original requirement, reconcile overlapping Hermes/ready packets, then split one testable behavior. Keep external/provider/owner prerequisites explicit.'
    write('catalog/backlog.json', cards)
    ids = Counter(row.ident for row in tables)
    diag = []
    for row in diagnostics:
        entry = asdict(row)
        # Preserve the unclassified table too: no silent loss behind parser diagnostics.
        block = []
        for line in source_lines[row.line - 1:]:
            if block and not line.strip().startswith('|'):
                break
            block.append(line)
        entry['source_table'] = '\n'.join(block)
        entry['planning_status'] = 'classification_required'
        diag.append(entry)
    write('catalog/coverage.json', {
        'source_sha': BASE, 'input_sha256': {p: file_hash(p) for p in INPUTS},
        'hermes_total': len(rows), 'recorded_counts': dict(Counter(r['status'] for r in rows)),
        'remaining_contracts': sum(r['status'] != 'equivalent' for r in rows),
        'review_overlay_ids': sorted(REVIEW),
        'checkbox_total': len(checkbox), 'checkbox_open': sum(not r.done for r in checkbox),
        'table_total': len(tables), 'table_statuses': dict(Counter(r.status for r in tables)),
        'backlog_open_records': len(cards),
        'duplicate_table_ids': {ident: [r.line for r in tables if r.ident == ident]
                                for ident, n in ids.items() if n > 1},
        'unclassified_tables': diag, 'excluded_tables': [asdict(r) for r in excluded],
        'note': 'Views overlap; counts must not be summed into a completion percentage. Source requirements are preserved, not independently reassessed. No generated contract is automatically a ready implementation packet.',
    })
    write('catalog/index.json', index)
    for packet_file in (PACKAGE / 'packets').glob('*.json'):
        for packet in json.loads(packet_file.read_text()):
            all_paths.update(packet['read_files'])
            all_paths.update(packet['owned_files'])
    write('catalog/source-fingerprints.json', {p: file_hash(p) for p in sorted(all_paths)})
    print(json.dumps({'contracts': len(index), 'remaining_contracts': sum(r['status'] != 'equivalent' for r in rows),
                      'backlog_records': len(cards), 'areas': len(groups)}))


if __name__ == '__main__':
    main()
