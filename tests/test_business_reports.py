import pytest

from agents.core.business.reports import ReportFilterError, build_report


def snapshot(**records):
    return {'connection_id':'a','connection_name':'Shop','synced_at':'2026-10-13T12:00:00Z',
            'complete':True,'coverage':'Import','records':records}


def test_sales_are_exact_per_currency_and_exclude_unpaid():
    result = build_report('sales_overview', [snapshot(orders=[
        {'id':'1','status':'completed','total':'0.10','currency':'EUR'},
        {'id':'2','status':'processing','total':'0.20','currency':'EUR'},
        {'id':'3','status':'completed','total':'10.00','currency':'RON'},
        {'id':'4','status':'cancelled','total':'99.00','currency':'EUR'},
    ])])
    assert result['metrics']['sales_by_currency'] == {'EUR':'0.30','RON':'10.00'}
    assert result['metrics']['paid_orders'] == 3
    assert result['metrics']['excluded_orders'] == 1


def test_partial_sources_and_missing_data_stay_visible():
    source = snapshot(orders=[])
    source['complete'] = False
    assert build_report('sales_overview',[source])['warnings']
    empty = build_report('sales_overview',[])
    assert empty['metrics'] == {}
    assert empty['warnings']


def test_stock_report_separates_unknown_stock():
    result=build_report('stock_watch',[snapshot(products=[
        {'id':'1','name':'A','stock_quantity':None},
        {'id':'2','name':'B','stock_quantity':-1},
        {'id':'3','name':'C','stock_quantity':10}])])
    assert result['metrics']['unknown_stock'] == 1
    assert result['metrics']['low_stock'] == 1
    assert result['rows'][0]['name'] == 'B'


def test_pipeline_never_combines_currencies():
    result=build_report('pipeline_review',[snapshot(deals=[
        {'id':'1','name':'A','amount':'10','currency':'EUR','stage':'new'},
        {'id':'2','name':'B','amount':'20','currency':'RON','stage':'new'}])])
    assert result['metrics']['value_by_currency'] == {'EUR':'10.00','RON':'20.00'}


def test_unknown_workflow_is_rejected():
    with pytest.raises(ValueError):
        build_report('run_shell',[])


def test_pipeline_missing_amount_is_excluded_with_visible_count():
    report = build_report('pipeline_review', [snapshot(deals=[
        {'id':'1','name':'Unknown','amount':None,'currency':'EUR','stage':'new'},
        {'id':'2','name':'Known','amount':'12','currency':'EUR','stage':'new'}])])
    assert report['metrics']['value_by_currency'] == {'EUR':'12.00'}
    assert report['metrics']['unknown_amount'] == 1
    assert any('sumă' in warning for warning in report['warnings'])


@pytest.mark.parametrize('start_date,end_date', [
    ('2026-10-14T00:00:00Z', None),
    ('2026-02-30', None),
    ('2026-10-14', '2026-10-13'),
    (42, None),
])
def test_sales_rejects_invalid_date_bounds_without_reflecting_input(start_date, end_date):
    with pytest.raises(ReportFilterError) as exc:
        build_report('sales_overview', [], start_date=start_date, end_date=end_date)
    assert str(start_date) not in str(exc.value)


@pytest.mark.parametrize('workflow_id', ['stock_watch', 'pipeline_review'])
def test_other_reports_reject_date_bounds(workflow_id):
    with pytest.raises(ReportFilterError):
        build_report(workflow_id, [], start_date='2026-10-14')


def test_sales_filter_includes_both_utc_calendar_boundaries_and_converts_offsets():
    report = build_report('sales_overview', [snapshot(orders=[
        {'id': 'before', 'status': 'completed', 'total': '1', 'currency': 'EUR',
         'created_at': '2026-10-13T23:59:59Z'},
        {'id': 'start', 'status': 'completed', 'total': '2', 'currency': 'EUR',
         'created_at': '2026-10-13T20:00:00-04:00'},
        {'id': 'end', 'status': 'processing', 'total': '3', 'currency': 'RON',
         'created_at': '2026-10-15T02:59:59+03:00'},
        {'id': 'after', 'status': 'completed', 'total': '4', 'currency': 'EUR',
         'created_at': '2026-10-15T00:00:00Z'},
    ])], start_date='2026-10-14', end_date='2026-10-14')
    assert report['filters'] == {'start_date': '2026-10-14', 'end_date': '2026-10-14'}
    assert [row['id'] for row in report['rows']] == ['start', 'end']
    assert report['metrics']['sales_by_currency'] == {'EUR': '2.00', 'RON': '3.00'}
    assert report['metrics']['paid_orders'] == 2


def test_sales_filter_counts_missing_and_invalid_dates_and_warns_about_naive_utc():
    report = build_report('sales_overview', [snapshot(orders=[
        {'id': 'missing', 'status': 'completed', 'total': '10', 'currency': 'EUR'},
        {'id': 'blank', 'status': 'completed', 'total': '20', 'currency': 'EUR', 'created_at': ''},
        {'id': 'invalid', 'status': 'completed', 'total': '30', 'currency': 'EUR', 'created_at': 'private-value'},
        {'id': 'date', 'status': 'completed', 'total': '1', 'currency': 'EUR', 'created_at': '2026-10-14'},
        {'id': 'naive', 'status': 'completed', 'total': '2', 'currency': 'EUR',
         'created_at': '2026-10-14T12:00:00'},
    ])], start_date='2026-10-14')
    assert report['metrics']['excluded_missing_date'] == 2
    assert report['metrics']['excluded_invalid_date'] == 1
    assert report['metrics']['paid_orders'] == 2
    assert report['metrics']['sales_by_currency'] == {'EUR': '3.00'}
    assert any('2' in warning and 'dată' in warning for warning in report['warnings'])
    assert any('1' in warning and 'invalid' in warning for warning in report['warnings'])
    assert any('UTC' in warning and '2' in warning for warning in report['warnings'])
    assert all('private-value' not in warning for warning in report['warnings'])


def test_sales_unfiltered_totals_keep_orders_without_dates():
    report = build_report('sales_overview', [snapshot(orders=[
        {'id': 'missing', 'status': 'completed', 'total': '10', 'currency': 'EUR'},
    ])])
    assert report['filters'] == {'start_date': None, 'end_date': None}
    assert report['metrics']['sales_by_currency'] == {'EUR': '10.00'}
    assert 'excluded_missing_date' not in report['metrics']


def test_relevant_sources_only_determine_coverage_and_stale_warnings():
    orders = snapshot(orders=[{'id': '1', 'status': 'completed', 'total': '2', 'currency': 'EUR'}])
    orders['kind'] = 'orders'
    orders['connection_name'] = 'Orders CSV'
    products = snapshot(products=[{'id': 'p', 'name': 'Product', 'stock_quantity': 2}])
    products.update(kind='products', connection_name='Products CSV', stale=True, complete=False)
    report = build_report('sales_overview', [orders, products])
    assert [item['source'] for item in report['coverage']] == ['Orders CSV']
    assert not any('Products CSV' in warning for warning in report['warnings'])
    assert not any('suprapuse' in warning for warning in report['warnings'])


def test_empty_known_relevant_source_stays_in_coverage():
    empty_woo = snapshot(orders=[], products=[])
    empty_woo.update(provider='woocommerce', connection_name='Woo', complete=False, stale=True)
    empty_hubspot = snapshot(orders=[], deals=[])
    empty_hubspot.update(provider='hubspot', connection_name='HubSpot', complete=False, stale=True)
    sales = build_report('sales_overview', [empty_woo, empty_hubspot])
    assert [item['source'] for item in sales['coverage']] == ['Woo']
    assert any('Woo' in warning for warning in sales['warnings'])
    assert not any('HubSpot' in warning for warning in sales['warnings'])
    pipeline = build_report('pipeline_review', [empty_woo, empty_hubspot])
    assert [item['source'] for item in pipeline['coverage']] == ['HubSpot']

    empty_csv = snapshot(orders=[])
    empty_csv.update(kind='orders', connection_name='Orders CSV', complete=False)
    csv_report = build_report('sales_overview', [empty_csv])
    assert [item['source'] for item in csv_report['coverage']] == ['Orders CSV']
    assert any('Orders CSV' in warning for warning in csv_report['warnings'])


def test_filtered_report_exposes_date_exclusions_when_no_rows_survive():
    report = build_report('sales_overview', [snapshot(orders=[
        {'id': 'missing', 'status': 'completed', 'total': '10', 'currency': 'EUR'},
    ])], end_date='2026-10-14')
    assert report['metrics'] == {'excluded_missing_date': 1, 'excluded_invalid_date': 0}
    assert report['rows'] == []
    assert 'intervalul selectat' in report['summary']


def test_unrepresentable_utc_timestamp_is_counted_as_invalid():
    report = build_report('sales_overview', [snapshot(orders=[
        {'id': 'overflow', 'status': 'completed', 'total': '10', 'currency': 'EUR',
         'created_at': '9999-12-31T23:59:59-01:00'},
    ])], start_date='2026-10-14')
    assert report['metrics']['excluded_invalid_date'] == 1
    assert report['rows'] == []


def test_nonempty_kind_rows_remain_relevant_without_source_metadata():
    report = build_report('stock_watch', [snapshot(products=[
        {'id': 'p', 'name': 'Product', 'stock_quantity': 2},
    ])])
    assert len(report['coverage']) == 1
