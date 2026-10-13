"""Deterministic company reports. Imported snapshots are evidence, not live totals."""
from collections import Counter, defaultdict
from decimal import Decimal

_WORKFLOWS = {
    'sales_overview': ('Situația vânzărilor', 'orders'),
    'stock_watch': ('Stocuri care necesită atenție', 'products'),
    'pipeline_review': ('Oportunități de vânzare', 'deals'),
}


def _totals(rows, field):
    totals = defaultdict(Decimal)
    for row in rows:
        if row[field] is not None:
            totals[row['currency']] += Decimal(row[field])
    return {key: format(value, '.2f') for key, value in sorted(totals.items())}


def build_report(workflow_id: str, snapshots: list[dict]) -> dict:
    if workflow_id not in _WORKFLOWS:
        raise ValueError('Raport necunoscut.')
    title, kind = _WORKFLOWS[workflow_id]
    result = {'workflow_id': workflow_id, 'title': title, 'summary': '', 'metrics': {},
              'rows': [], 'coverage': [], 'warnings': []}
    if not snapshots:
        result['summary'] = 'Conectează o sursă sau importă un fișier CSV pentru acest raport.'
        result['warnings'].append('Nu există date sincronizate.')
        return result
    rows = []
    for source in snapshots:
        label = source.get('connection_name', source.get('connection_id', 'Sursă'))
        result['coverage'].append({'source': label, 'synced_at': source.get('synced_at'),
                                   'description': source.get('coverage', ''), 'complete': source.get('complete', False)})
        if not source.get('complete', False):
            result['warnings'].append(f'{label}: date parțiale; totalurile acoperă doar înregistrările importate.')
        if source.get('stale') or source.get('status') == 'error':
            result['warnings'].append(f'{label}: ultima sincronizare a eșuat; sunt afișate datele anterioare.')
        rows.extend({**row, 'source': label} for row in source.get('records', {}).get(kind, []))
    if len(snapshots) > 1:
        result['warnings'].append('Sursele sunt cumulate fără reconciliere între sisteme; evită importurile suprapuse.')
    if not rows:
        result['summary'] = 'Sursele sincronizate nu conțin înregistrări pentru acest raport.'
        result['warnings'].append(f'Nu există înregistrări de tip {kind}.')
        return result
    if kind == 'orders':
        paid = [row for row in rows if row['status'] in {'completed', 'processing'}]
        result['metrics'] = {'paid_orders': len(paid), 'excluded_orders': len(rows)-len(paid),
                             'sales_by_currency': _totals(paid, 'total')}
        result['rows'] = paid[:100]
        result['summary'] = f'{len(paid)} comenzi în status completed/processing. Valoarea include taxele și transportul din totalul sursei; nu reprezintă profit.'
        result['warnings'].append('Statusul comenzii nu dovedește încasarea bancară. Sunt excluse comenzile cu alte statusuri. Rambursările parțiale nu sunt reconciliate; verifică sistemul contabil.')
    elif kind == 'products':
        low = [row for row in rows if row['stock_quantity'] is not None and row['stock_quantity'] <= 3]
        result['metrics'] = {'products': len(rows), 'low_stock': len(low),
                             'unknown_stock': sum(row['stock_quantity'] is None for row in rows)}
        result['rows'] = sorted(low, key=lambda row: row['stock_quantity'])[:100]
        result['summary'] = f'{len(low)} produse cu stoc de maximum 3 unități. Produsele cu stoc necunoscut necesită verificare separată.'
        result['warnings'].append('Variațiile WooCommerce nu sunt importate separat; stocul pe mărime/culoare se verifică în magazin.')
    else:
        result['metrics'] = {'deals': len(rows), 'value_by_currency': _totals(rows, 'amount'),
                             'unknown_amount': sum(row['amount'] is None for row in rows),
                             'by_stage': dict(Counter(row['stage'] for row in rows))}
        result['rows'] = rows[:100]
        result['summary'] = f'{len(rows)} oportunități, grupate pe etapele din CRM; valorile includ toate etapele și nu sunt venit realizat.'
        if result['metrics']['unknown_amount']:
            result['warnings'].append('Oportunitățile fără sumă sunt excluse din totaluri; valoarea lor rămâne necunoscută.')
        if any(row['currency'] == 'XXX' for row in rows):
            result['warnings'].append('XXX indică moneda nespecificată de CRM. Confirmă moneda înainte de utilizarea sumelor.')
    if len(rows) > 100:
        result['warnings'].append('Tabelul afișează maximum 100 rânduri; indicatorii folosesc toate datele importate.')
    return result
