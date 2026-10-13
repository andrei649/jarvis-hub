import pytest

from agents.core.business.reports import build_report


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
