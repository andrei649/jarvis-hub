"""Read one bounded planning packet. Never execute commands or change task/verdict state."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[3]


def read(path):
    return json.loads((PACKAGE / path).read_text())


def packets():
    return [t for p in sorted((PACKAGE / 'packets').glob('*.json'))
            for t in json.loads(p.read_text())]


def contracts():
    return [t for p in sorted((PACKAGE / 'catalog/contracts').glob('*.json'))
            for t in json.loads(p.read_text())]


def validate(check_source=False):
    issues = []
    tasks = packets()
    by_id = {t['id']: t for t in tasks}
    if len(by_id) != len(tasks):
        issues.append('duplicate packet id')
    required = {'id', 'title', 'spec_state', 'priority', 'risk', 'goal', 'non_goals',
                'depends_on', 'owned_files', 'read_files', 'interfaces', 'acceptance',
                'steps', 'commands', 'review_focus', 'stop_conditions', 'rollback',
                'source_refs', 'hermes_ids', 'backlog_ids'}
    for task in tasks:
        ident = task['id']
        if required - task.keys():
            issues.append(f'{ident}: missing fields {sorted(required - task.keys())}')
        if task['spec_state'] not in {'ready', 'needs_design', 'external'}:
            issues.append(f'{ident}: invalid state')
        if not task['acceptance'] or not task['commands']:
            issues.append(f'{ident}: no acceptance/verification')
        for case in task['acceptance']:
            if not {'case', 'given', 'when', 'then'} <= case.keys():
                issues.append(f'{ident}: incomplete acceptance case')
        for dep in task['depends_on']:
            if dep not in by_id:
                issues.append(f'{ident}: unknown dependency {dep}')
        for hid in task['hermes_ids']:
            if hid not in {f'H{n:03}' for n in range(1, 698)}:
                issues.append(f'{ident}: unknown Hermes id {hid}')
    visiting, visited = set(), set()

    def visit(ident):
        if ident in visiting:
            issues.append('dependency cycle at ' + ident)
            return
        if ident in visited or ident not in by_id:
            return
        visiting.add(ident)
        for dep in by_id[ident]['depends_on']:
            visit(dep)
        visiting.remove(ident)
        visited.add(ident)

    for ident in by_id:
        visit(ident)
    cs = contracts()
    coverage = read('catalog/coverage.json')
    if sorted(c['id'] for c in cs) != [f'H{n:03}' for n in range(1, 698)]:
        issues.append('697-contract coverage is not exact')
    if dict(Counter(c['recorded_status'] for c in cs)) != coverage['recorded_counts']:
        issues.append('recorded-count mismatch')
    bs = read('catalog/backlog.json')
    if len(bs) != coverage['backlog_open_records'] or len({b['id'] for b in bs}) != len(bs):
        issues.append('backlog coverage/identity mismatch')
    if check_source:
        fingerprints = read('catalog/source-fingerprints.json')
        fingerprints.update(coverage['input_sha256'])
        for name, expected in fingerprints.items():
            path = ROOT / name
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if actual != expected:
                issues.append('source changed; refresh catalog: ' + name)
    return {'ok': not issues, 'packets': len(tasks), 'contracts': len(cs),
            'backlog_records': len(bs), 'errors': issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('stats')
    listing = sub.add_parser('list')
    listing.add_argument('--state', choices=['ready', 'needs_design', 'external'])
    showing = sub.add_parser('show')
    showing.add_argument('id')
    showing.add_argument('--part', type=int, default=1)
    showing.add_argument('--chars', type=int, default=9000)
    selecting = sub.add_parser('next')
    selecting.add_argument('--done', nargs='*', default=[], help='IDs accepted by the reviewer, not self-reported passes')
    selecting.add_argument('--active', nargs='*', default=[])
    selecting.add_argument('--limit', type=int, default=2)
    checking = sub.add_parser('validate')
    checking.add_argument('--check-source', action='store_true')
    args = parser.parse_args()
    tasks = packets()
    if args.command == 'validate':
        result = validate(args.check_source)
        print(json.dumps(result, indent=2))
        return 0 if result['ok'] else 1
    if args.command == 'stats':
        cov = read('catalog/coverage.json')
        print(json.dumps({'source_sha': cov['source_sha'], 'recorded_hermes': cov['recorded_counts'],
                          'remaining_contracts': cov['remaining_contracts'],
                          'review_overlay_ids': cov['review_overlay_ids'],
                          'backlog_open_records': cov['backlog_open_records'],
                          'packets_by_spec_state': dict(Counter(t['spec_state'] for t in tasks)),
                          'note': 'Specification readiness is not implementation completion.'}, indent=2))
        return 0
    if args.command == 'list':
        for task in tasks:
            if not args.state or task['spec_state'] == args.state:
                print(f"{task['id']} {task['priority']} {task['spec_state']:12} {task['title']}")
        return 0
    if args.command == 'show':
        candidates = tasks + contracts() + read('catalog/backlog.json')
        item = next((x for x in candidates if x['id'] == args.id), None)
        if item is None:
            parser.error('unknown id; use list or catalog/index.json')
        if not 500 <= args.chars <= 16000 or args.part < 1:
            parser.error('chars must be 500..16000; part >= 1')
        raw = json.dumps(item, ensure_ascii=False, indent=2)
        count = (len(raw) + args.chars - 1) // args.chars
        if args.part > count:
            parser.error(f'only {count} parts')
        print(f'[{args.id}: part {args.part}/{count}; read all parts before implementation]')
        print(raw[(args.part - 1) * args.chars:args.part * args.chars])
        return 0
    validation = validate(check_source=True)
    if not validation['ok']:
        print(json.dumps(validation, indent=2))
        return 1
    by_id = {t['id']: t for t in tasks}
    unknown = (set(args.done) | set(args.active)) - by_id.keys()
    if unknown:
        parser.error('unknown task ids: ' + ', '.join(sorted(unknown)))
    done, active = set(args.done), set(args.active)
    if done & active:
        parser.error('a task cannot be both done and active')
    locks = {f for ident in active for f in by_id[ident]['owned_files']}
    chosen = []
    for task in sorted(tasks, key=lambda t: (t['priority'], t['id'])):
        if (task['spec_state'] != 'ready' or task['id'] in done | active
                or not set(task['depends_on']) <= done or set(task['owned_files']) & locks):
            continue
        chosen.append({'id': task['id'], 'title': task['title'], 'risk': task['risk'],
                       'owned_files': task['owned_files']})
        locks.update(task['owned_files'])
        if len(chosen) >= max(1, min(args.limit, 8)):
            break
    print(json.dumps({'assignments': chosen, 'instruction': 'Read full packet and check source drift first; no commands were executed.'}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
