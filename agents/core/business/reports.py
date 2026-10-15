"""Deterministic company reports. Imported snapshots are evidence, not live totals."""
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

_WORKFLOWS = {
    'sales_overview': ('Situația vânzărilor', 'orders'),
    'stock_watch': ('Stocuri care necesită atenție', 'products'),
    'pipeline_review': ('Oportunități de vânzare', 'deals'),
}


class ReportFilterError(ValueError):
    """A fixed, safe report-filter error suitable for the operator UI."""


def _date_bound(value: str | None) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ReportFilterError('Folosește date calendaristice în format YYYY-MM-DD.')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ReportFilterError('Folosește date calendaristice valide în format YYYY-MM-DD.') from None


def _relevant(source: dict, kind: str) -> bool:
    source_kind = source.get('kind')
    if source_kind in {'orders', 'products', 'deals'}:
        return source_kind == kind
    provider = source.get('provider')
    if provider == 'woocommerce':
        return kind in {'orders', 'products'}
    if provider == 'hubspot':
        return kind == 'deals'
    return bool(source.get('records', {}).get(kind))


def _filter_sales_dates(rows: list[dict], start: date | None, end: date | None):
    selected = []
    missing = invalid = assumed_utc = 0
    for row in rows:
        value = row.get('created_at')
        if value is None or isinstance(value, str) and not value.strip():
            missing += 1
            continue
        if not isinstance(value, str):
            invalid += 1
            continue
        try:
            timestamp = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                timestamp = timestamp.replace(tzinfo=UTC)
                assumed_utc += 1
            day = timestamp.astimezone(UTC).date()
        except (ValueError, OverflowError):
            invalid += 1
            continue
        if (start is None or day >= start) and (end is None or day <= end):
            selected.append(row)
    return selected, missing, invalid, assumed_utc


def _totals(rows, field):
    totals = defaultdict(Decimal)
    for row in rows:
        if row[field] is not None:
            totals[row['currency']] += Decimal(row[field])
    return {key: format(value, '.2f') for key, value in sorted(totals.items())}


def build_report(workflow_id: str, snapshots: list[dict], *, start_date: str | None = None,
                 end_date: str | None = None) -> dict:
    if workflow_id not in _WORKFLOWS:
        raise ValueError('Raport necunoscut.')
    title, kind = _WORKFLOWS[workflow_id]
    if kind != 'orders' and (start_date is not None or end_date is not None):
        raise ReportFilterError('Filtrul de dată este disponibil doar pentru raportul de vânzări.')
    start, end = _date_bound(start_date), _date_bound(end_date)
    if start is not None and end is not None and start > end:
        raise ReportFilterError('Data de început trebuie să fie înaintea sau egală cu data de sfârșit.')
    result = {'workflow_id': workflow_id, 'title': title, 'summary': '', 'metrics': {},
              'rows': [], 'coverage': [], 'warnings': [],
              'filters': {'start_date': start_date, 'end_date': end_date}}
    if not snapshots:
        result['summary'] = 'Conectează o sursă sau importă un fișier CSV pentru acest raport.'
        result['warnings'].append('Nu există date sincronizate.')
        return result
    rows = []
    relevant = [source for source in snapshots if _relevant(source, kind)]
    for source in relevant:
        label = source.get('connection_name', source.get('connection_id', 'Sursă'))
        result['coverage'].append({'source': label, 'synced_at': source.get('synced_at'),
                                   'description': source.get('coverage', ''), 'complete': source.get('complete', False)})
        if not source.get('complete', False):
            result['warnings'].append(f'{label}: date parțiale; totalurile acoperă doar înregistrările importate.')
        if source.get('stale') or source.get('status') == 'error':
            result['warnings'].append(f'{label}: ultima sincronizare a eșuat; sunt afișate datele anterioare.')
        rows.extend({**row, 'source': label} for row in source.get('records', {}).get(kind, []))
    if len(relevant) > 1:
        result['warnings'].append('Sursele sunt cumulate fără reconciliere între sisteme; evită importurile suprapuse.')
    if kind == 'orders' and (start is not None or end is not None):
        rows, missing, invalid, assumed_utc = _filter_sales_dates(rows, start, end)
        result['metrics'].update(excluded_missing_date=missing, excluded_invalid_date=invalid)
        if missing:
            result['warnings'].append(f'{missing} înregistrări fără dată au fost excluse din interval.')
        if invalid:
            result['warnings'].append(f'{invalid} înregistrări cu dată invalidă au fost excluse din interval.')
        if assumed_utc:
            result['warnings'].append(f'{assumed_utc} date fără fus orar au fost interpretate ca UTC.')
    if not rows:
        if kind == 'orders' and (start is not None or end is not None):
            result['summary'] = 'Nu există comenzi cu dată validă în intervalul selectat.'
            result['warnings'].append('Nicio comandă nu se încadrează în filtrul de dată.')
        else:
            result['summary'] = 'Sursele sincronizate nu conțin înregistrări pentru acest raport.'
            result['warnings'].append(f'Nu există înregistrări de tip {kind}.')
        return result
    if kind == 'orders':
        paid = [row for row in rows if row['status'] in {'completed', 'processing'}]
        result['metrics'].update(paid_orders=len(paid), excluded_orders=len(rows)-len(paid),
                                 sales_by_currency=_totals(paid, 'total'))
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
