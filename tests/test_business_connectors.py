from contextlib import asynccontextmanager

import httpx
import pytest

from agents.core.business.connectors import (
    BusinessHTTPClient,
    ConnectorError,
    fetch_snapshot,
    parse_csv,
    validate_connection,
)


@pytest.mark.parametrize('url', ['http://shop.example', 'https://u:p@shop.example',
    'https://127.0.0.1', 'https://169.254.169.254', 'https://shop.example?token=secret',
    'https://shop.example/#x', 'https://shop.example\\@evil.example'])
def test_connection_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        validate_connection('woocommerce', url, {'consumer_key': 'ck_x', 'consumer_secret': 'cs_x'})


def test_hubspot_origin_is_fixed():
    assert validate_connection('hubspot', '', {'access_token': 'private'}) == 'https://api.hubapi.com'
    with pytest.raises(ValueError):
        validate_connection('hubspot', 'https://other.example', {'access_token': 'private'})


def test_credentials_schema_rejects_missing_and_extra():
    with pytest.raises(ValueError):
        validate_connection('woocommerce', 'https://shop.example', {'consumer_key': 'x'})
    with pytest.raises(ValueError):
        validate_connection('hubspot', '', {'access_token': 'x', 'extra': 'y'})


def test_transport_is_bound_to_approved_origin():
    client = BusinessHTTPClient('woocommerce', 'https://shop.example')
    assert client._manifest_mode('https://shop.example/wp-json/wc/v3/orders') == 'public'
    with pytest.raises(PermissionError):
        client._manifest_mode('https://elsewhere.example/orders')


def test_csv_preserves_money_and_unknown_stock():
    data = parse_csv('id,status,total,currency,created_at\n1,completed,12.30,ron,2026-10-13\n', 'orders')
    assert data['records']['orders'][0]['total'] == '12.30'
    assert data['records']['orders'][0]['currency'] == 'RON'
    products = parse_csv('id,name,stock_quantity\n1,Coat,\n2,Boots,-2\n', 'products')
    assert products['records']['products'][0]['stock_quantity'] is None
    assert products['records']['products'][1]['stock_quantity'] == -2


@pytest.mark.parametrize('body', ['id,status,total,currency\n1,completed,NaN,EUR\n',
    'id,status,total,currency\n1,completed,Infinity,EUR\n',
    'id,status,total,currency\n1,completed,-2,EUR\n',
    'id,status,total,currency\n1,completed,2,nope\n',
    'id,status,total,currency\n1,completed,2,EUR\n1,completed,3,EUR\n',
    'id,total,currency\n1,2,EUR\n'])
def test_csv_refuses_invalid_or_ambiguous_rows(body):
    with pytest.raises(ValueError):
        parse_csv(body, 'orders')


def test_csv_refuses_more_than_500_rows():
    with pytest.raises(ValueError, match='500'):
        parse_csv('id,name,stock_quantity\n' + ''.join(f'{i},Item,1\n' for i in range(501)), 'products')


async def test_woo_sync_maps_records_and_follows_only_bounded_pages(monkeypatch):
    calls = []
    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith('/orders'):
            yield httpx.Response(200, json=[{'id': kwargs['params']['page'], 'status':'completed',
                'total':'42.50', 'currency':'RON', 'date_created':'2026-10-13'}],
                headers={'X-WP-TotalPages':'9'}, request=httpx.Request('GET',url))
            return
        yield httpx.Response(200, json=[{'id':1,'name':'Coat','stock_quantity':2}],
            headers={'X-WP-TotalPages':'1'}, request=httpx.Request('GET',url))
    monkeypatch.setattr(BusinessHTTPClient, 'stream', stream)
    result = await fetch_snapshot('woocommerce', 'https://shop.example',
        {'consumer_key':'ck_x','consumer_secret':'cs_x'})
    assert len(result['records']['orders']) == 5
    assert result['complete'] is False
    assert len(calls) == 6
    assert all('consumer_secret' not in kwargs.get('params', {}) for _, kwargs in calls)


async def test_provider_error_does_not_leak_credentials_or_response(monkeypatch):
    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        yield httpx.Response(401, text='secret-user-token', request=httpx.Request('GET',url))
    monkeypatch.setattr(BusinessHTTPClient, 'stream', stream)
    with pytest.raises(ConnectorError) as exc:
        await fetch_snapshot('hubspot', '', {'access_token':'secret-user-token'})
    assert 'secret-user-token' not in str(exc.value)
    assert '401' in str(exc.value)


async def test_hubspot_missing_amount_stays_unknown(monkeypatch):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        yield httpx.Response(200, json={'results': [{'id': '1', 'properties': {
            'dealname': 'Unquoted', 'amount': None, 'dealstage': 'new'}}]})
    monkeypatch.setattr(BusinessHTTPClient, 'stream', stream)
    result = await fetch_snapshot('hubspot', '', {'access_token': 'test'})
    assert result['records']['deals'][0]['amount'] is None
    assert result['records']['deals'][0]['currency'] == 'XXX'


async def test_stream_stops_before_reading_unbounded_response(monkeypatch):
    from contextlib import asynccontextmanager
    consumed = []
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(10):
                consumed.append(index)
                yield b' ' * 1_000_000
    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        yield httpx.Response(200, stream=Body())
    monkeypatch.setattr(BusinessHTTPClient, 'stream', stream)
    with pytest.raises(ConnectorError, match='mare'):
        await fetch_snapshot('hubspot', '', {'access_token': 'test'})
    assert len(consumed) == 5


def test_csv_validation_has_safe_row_and_column():
    from agents.core.business.connectors import CsvImportError
    with pytest.raises(CsvImportError) as failure:
        parse_csv('id,status,total,currency\na,completed,10,EUR\nb,completed,SECRET-CELL,EUR', 'orders')
    assert '3' in str(failure.value) and 'total' in str(failure.value)
    assert 'SECRET-CELL' not in str(failure.value)


async def test_woo_prefers_utc_timestamp_for_report_filters(monkeypatch):
    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        items = ([{'id': 1, 'status': 'completed', 'total': '1', 'currency': 'EUR',
                  'date_created': '2026-10-02T00:30:00', 'date_created_gmt': '2026-10-01T21:30:00'}]
                 if url.endswith('/orders') else [])
        yield httpx.Response(200, json=items, headers={'X-WP-TotalPages': '1'})
    monkeypatch.setattr(BusinessHTTPClient, 'stream', stream)
    data = await fetch_snapshot('woocommerce', 'https://shop.example', {'consumer_key': 'key', 'consumer_secret': 'secret'})
    assert data['records']['orders'][0]['created_at'] == '2026-10-01T21:30:00Z'
