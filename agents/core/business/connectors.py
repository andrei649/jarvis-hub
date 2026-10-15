"""Bounded read-only company data adapters; credentials never travel in URLs."""
from __future__ import annotations

import base64
import csv
import io
import ipaddress
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx

from agents.core.http_client import PluginEgressError, PluginHTTPClient, PluginTimeouts

KINDS = ('orders', 'products', 'deals')
MAX_RECORDS = 500
MAX_CSV_BYTES = 1_000_000
_FIELDS = {'woocommerce': {'consumer_key', 'consumer_secret'}, 'hubspot': {'access_token'}, 'csv': set()}


class ConnectorError(ValueError):
    """A sanitized error suitable for the operator UI."""


class CsvImportError(ValueError):
    """Safe import diagnostics: row/field names, never cell values."""


def _field_value(field, validator, value):
    try:
        return validator(value)
    except ValueError as exc:
        # Only internal validators with fixed messages are accepted here.
        raise CsvImportError(f'Câmpul {field}: {exc}') from None


def validate_connection(provider: str, base_url: str, credentials: dict) -> str:
    if provider not in _FIELDS:
        raise ValueError('Conector necunoscut.')
    if not isinstance(credentials, dict) or set(credentials) != _FIELDS[provider]:
        raise ValueError('Completează exact câmpurile de autentificare ale conectorului.')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 4096 or '\n' in v or '\r' in v
           for v in credentials.values()):
        raise ValueError('Date de autentificare invalide.')
    if provider == 'csv':
        if base_url:
            raise ValueError('Importul CSV nu utilizează un URL.')
        return ''
    base_url = base_url.strip()
    if provider == 'hubspot':
        if base_url.rstrip('/') not in ('', 'https://api.hubapi.com'):
            raise ValueError('HubSpot utilizează exclusiv https://api.hubapi.com.')
        return 'https://api.hubapi.com'
    try:
        url = urlsplit(base_url)
        port = url.port
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or port not in (None, 443)
                or re.search(r'[\s\\\x00-\x1f\x7f]', base_url)
                or '%' in url.netloc or '..' in url.path):
            raise ValueError('invalid URL')
        host = url.hostname.lower().rstrip('.')
        if host in {'localhost', 'localhost.localdomain'} or host.endswith(('.local', '.localhost')):
            raise ValueError('private host')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host):
                raise ValueError('invalid host') from None
        else:
            if not address.is_global:
                raise ValueError('private address')
    except ValueError:
        raise ValueError('Folosește un URL HTTPS public, fără autentificare, parametri sau fragmente.') from None
    return base_url.rstrip('/')


class BusinessHTTPClient(PluginHTTPClient):
    """Reuse Nerva's pinned DNS/TLS transport and kernel; further restrict origin."""
    def __init__(self, provider: str, base_url: str):
        super().__init__(f'business_{provider}', timeouts=PluginTimeouts(connect=5, read=15, total=20))
        parsed = urlsplit(base_url)
        self._origin = (parsed.scheme, parsed.hostname, parsed.port or 443)

    def _manifest_mode(self, url: str) -> str:
        parsed = urlsplit(url)
        if ((parsed.scheme, parsed.hostname, parsed.port or 443) != self._origin
                or parsed.username or parsed.password):
            raise PluginEgressError('Conectorul poate accesa doar adresa configurată.')
        # This adapter's explicit admin-configured origin is its whole allowlist.
        # Always public: the parent transport refuses private DNS answers/rebinding.
        return 'public'


def _text(value, limit=200):
    return str(value or '').strip()[:limit]


def _money(value) -> str:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal('1000000000000'):
            raise ValueError('invalid amount')
        if amount != amount.quantize(Decimal('0.01')):
            raise ValueError('too many decimals')
        return format(amount.quantize(Decimal('0.01')), 'f')
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Sumă invalidă: folosește un număr pozitiv cu maximum două zecimale.') from None


def _currency(value) -> str:
    currency = _text(value).upper()
    if not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError('Moneda trebuie să fie un cod de trei litere, de exemplu RON sau EUR.')
    return currency


def _stock(value):
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > 1_000_000_000 or number != int(number):
            raise ValueError('invalid stock')
        return int(number)
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError('Stocul trebuie să fie un număr întreg sau un câmp gol.') from None


def _normalize(kind: str, item: dict) -> dict:
    ident = _text(item.get('id'))
    if not ident:
        raise ValueError('Fiecare înregistrare trebuie să aibă un id.')
    if kind == 'orders':
        status = _text(item.get('status'))
        if not status:
            raise ValueError('Comenzile necesită un status.')
        return {'id': ident, 'status': status, 'total': _field_value('total', _money, item.get('total')),
                'currency': _field_value('currency', _currency, item.get('currency')), 'created_at': _text(item.get('created_at'))}
    if kind == 'products':
        return {'id': ident, 'name': _text(item.get('name')), 'stock_quantity': _field_value('stock_quantity', _stock, item.get('stock_quantity'))}
    return {'id': ident, 'name': _text(item.get('name')), 'amount': _field_value('amount', _money, item.get('amount')),
            'currency': _field_value('currency', _currency, item.get('currency')), 'stage': _text(item.get('stage')) or 'unknown'}


def parse_csv(text: str, kind: str) -> dict:
    if kind not in KINDS or not isinstance(text, str) or len(text.encode('utf-8')) > MAX_CSV_BYTES:
        raise CsvImportError('Tip CSV invalid sau fișier prea mare (maximum 1 MB).')
    required = {'orders': {'id','status','total','currency'}, 'products': {'id','name','stock_quantity'},
                'deals': {'id','name','amount','currency','stage'}}[kind]
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), strict=True)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not required.issubset(fields):
            raise CsvImportError('Antet invalid. Folosește virgulă ca separator și coloanele: ' + ', '.join(sorted(required)))
        rows, seen = [], set()
        for row in reader:
            if len(rows) >= MAX_RECORDS:
                raise CsvImportError('Importul acceptă maximum 500 de rânduri.')
            if None in row or any(row.get(key) is None for key in required):
                raise CsvImportError(f'Rândul {reader.line_num}: numărul de coloane diferă față de antet.')
            try:
                normalized = _normalize(kind, row)
            except ValueError as exc:
                raise CsvImportError(f'Rândul {reader.line_num}: {exc}') from None
            if normalized['id'] in seen:
                raise CsvImportError(f'Rândul {reader.line_num}: ID duplicat în import.')
            seen.add(normalized['id'])
            rows.append(normalized)
    except csv.Error:
        raise CsvImportError('CSV invalid. Folosește virgulă ca separator și ghilimele pentru text.') from None
    if not rows:
        raise CsvImportError('CSV-ul nu conține înregistrări.')
    return {'kind': kind, 'records': {key: rows if key == kind else [] for key in KINDS},
            'complete': True, 'coverage': f'Import CSV explicit: {len(rows)} înregistrări; perioada este cea din fișier.'}


async def _get_json(client, url, **kwargs):
    async with client.stream('GET', url, follow_redirects=False,
                             timeout=client.timeouts.to_httpx_timeout(), **kwargs) as response:
        if not 200 <= response.status_code < 300:
            repair = {401: 'Verifică cheia sau tokenul de acces.',
                      403: 'Verifică permisiunile de citire ale aplicației.',
                      404: 'Verifică adresa magazinului și activarea API-ului.',
                      429: 'Limita furnizorului a fost atinsă. Reîncearcă mai târziu.'}
            raise ConnectorError(f'Conectarea a eșuat (HTTP {response.status_code}). '
                                 + repair.get(response.status_code, 'Verifică disponibilitatea serviciului.'))
        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65_536):
            if len(body) + len(chunk) > 4_000_000:
                raise ConnectorError('Răspuns prea mare; restrânge datele din sistemul sursă.')
            body.extend(chunk)
        try:
            return json.loads(body), response.headers
        except (ValueError, UnicodeError):
            raise ConnectorError('Sursa a trimis un răspuns JSON invalid.') from None


async def fetch_snapshot(provider: str, base_url: str, credentials: dict) -> dict:
    base_url = validate_connection(provider, base_url, credentials)
    if provider == 'csv':
        raise ConnectorError('Reimportă fișierul CSV pentru a actualiza datele.')
    client = BusinessHTTPClient(provider, base_url)
    records = {key: [] for key in KINDS}
    complete = True
    try:
        if provider == 'woocommerce':
            token = base64.b64encode(f"{credentials['consumer_key']}:{credentials['consumer_secret']}".encode()).decode()
            for kind in ('orders', 'products'):
                seen = set()
                for page in range(1, 6):
                    items, headers = await _get_json(client, f'{base_url}/wp-json/wc/v3/{kind}',
                        headers={'Authorization': f'Basic {token}'},
                        params={'page': page, 'per_page': 100, 'orderby': 'id', 'order': 'desc'})
                    if not isinstance(items, list) or len(items) > 100:
                        raise ConnectorError('Format de date WooCommerce invalid.')
                    for item in items:
                        if not isinstance(item, dict):
                            raise ValueError('invalid record')
                        value = dict(item)
                        utc_created = value.get('date_created_gmt')
                        value['created_at'] = (str(utc_created).removesuffix('Z') + 'Z'
                                               if utc_created else value.get('date_created', ''))
                        row = _normalize(kind, value)
                        if row['id'] in seen:
                            complete = False
                            continue
                        seen.add(row['id'])
                        records[kind].append(row)
                    pages = headers.get('X-WP-TotalPages')
                    if pages is not None:
                        total_pages = int(pages)
                        if total_pages <= page:
                            break
                        if page == 5:
                            complete = False
                    elif len(items) < 100:
                        break
                    elif page == 5:
                        complete = False
        else:
            after = None
            seen = set()
            for page in range(5):
                params = {'limit': 100, 'properties': 'dealname,amount,dealstage,deal_currency_code', 'archived': 'false'}
                if after is not None:
                    params['after'] = after
                payload, _ = await _get_json(client, f'{base_url}/crm/v3/objects/deals',
                    headers={'Authorization': f"Bearer {credentials['access_token']}"}, params=params)
                if not isinstance(payload, dict) or not isinstance(payload.get('results'), list) or len(payload['results']) > 100:
                    raise ConnectorError('Format de date HubSpot invalid.')
                for item in payload['results']:
                    props = item.get('properties', {})
                    # Currency can be absent in single-currency HubSpot accounts.
                    # Keep it explicitly unknown rather than infer EUR from the workspace.
                    row = _normalize('deals', {'id': item['id'], 'name': props.get('dealname'),
                        'amount': props.get('amount') or '0', 'currency': props.get('deal_currency_code') or 'XXX',
                        'stage': props.get('dealstage')})
                    if props.get('amount') in (None, ''):
                        row['amount'] = None
                    if row['id'] in seen:
                        complete = False
                        continue
                    seen.add(row['id'])
                    records['deals'].append(row)
                after = (payload.get('paging') or {}).get('next', {}).get('after')
                if after is None:
                    break
                if not isinstance(after, (str, int)) or len(str(after)) > 200:
                    raise ConnectorError('Cursor HubSpot invalid.')
                if page == 4:
                    complete = False
    except ConnectorError:
        raise
    except (httpx.HTTPError, PermissionError, ValueError, KeyError, TypeError, AttributeError):
        raise ConnectorError('Sincronizare indisponibilă: verifică adresa, drepturile și formatul datelor.') from None
    finally:
        await client.close()
    return {'records': records, 'complete': complete,
            'coverage': 'Instantaneu la sincronizare, maximum 500 înregistrări per categorie; fără filtru de perioadă.'}
