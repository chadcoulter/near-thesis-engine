import datetime
import sys
import types
from unittest.mock import Mock

import pytest
import requests

import fetch_data


def fake_bigquery(monkeypatch, estimate=100):
    queries = []
    def query(sql, job_config):
        queries.append((sql,job_config))
        if getattr(job_config,'dry_run',False):
            return types.SimpleNamespace(total_bytes_processed=estimate)
        row = {'receiver_id':'fixture.near','call_count':2} if 'receipt_actions' in sql else {
            'block_date':datetime.date(2026,11,1),
            'daily_active_accounts' if 'DISTINCT' in sql else 'tx_count':3}
        return types.SimpleNamespace(result=lambda:[row],job_id='fixture-job',total_bytes_processed=estimate,
                                     total_bytes_billed=estimate,cache_hit=False)
    bigquery = types.ModuleType('google.cloud.bigquery')
    bigquery.Client = lambda **kwargs:Mock(query=query,project=kwargs.get('project','fixture-project'))
    bigquery.QueryJobConfig = lambda **kwargs:types.SimpleNamespace(**kwargs)
    bigquery.ScalarQueryParameter = lambda name,type_,value:types.SimpleNamespace(name=name,type_=type_,value=value)
    google = types.ModuleType('google'); google.__path__ = []
    cloud = types.ModuleType('google.cloud'); cloud.__path__ = []; cloud.bigquery = bigquery
    monkeypatch.setitem(sys.modules,'google',google)
    monkeypatch.setitem(sys.modules,'google.cloud',cloud)
    monkeypatch.setitem(sys.modules,'google.cloud.bigquery',bigquery)
    return queries


def test_bigquery_actual_tables_queries_and_date_serialization(monkeypatch):
    queries = fake_bigquery(monkeypatch)
    monkeypatch.setenv('GOOGLE_CLOUD_PROJECT','fixture-sandbox')
    bundle = fetch_data.fetch_bigquery()
    assert bundle['demo'] is False
    assert len(queries) == 6
    assert all(getattr(config,'dry_run',False) for _,config in queries[:3])
    assert all(config.maximum_bytes_billed == 20000000000 for _,config in queries[3:])
    assert 'transactions`' in queries[0][0] and 'signer_account_id' in queries[0][0]
    assert 'receipt_actions`' in queries[2][0] and "action_kind = 'FUNCTION_CALL'" in queries[2][0]
    assert all('WHERE block_date >= @start_date AND block_date < @end_date' in sql for sql,_ in queries)
    assert bundle['data']['daily_active_accounts'][0]['block_date'] == '2026-11-01'
    assert bundle['queries']['daily_active_accounts'] == queries[0][0]
    assert bundle['query_project'] == 'fixture-sandbox'
    assert sum(bundle['dry_run_bytes'].values()) == 300
    assert bundle['jobs']['daily_active_accounts']['job_id'] == 'fixture-job'


def test_bigquery_refuses_oversize_before_any_data_query(monkeypatch):
    queries=fake_bigquery(monkeypatch,estimate=20000000001)
    result=fetch_data.fetch_bigquery()
    assert result['demo'] is True
    assert 'exceeds BQ_MAX_BYTES_BILLED' in result['error']
    assert all(getattr(config,'dry_run',False) for _,config in queries)
    assert all(rows == [] for rows in result['data'].values())


def test_bigquery_total_budget_checked_before_data_queries(monkeypatch):
    monkeypatch.setenv('BQ_MAX_TOTAL_BYTES','200')
    queries=fake_bigquery(monkeypatch,estimate=100)
    result=fetch_data.fetch_bigquery()
    assert result['demo'] is True
    assert 'BQ_MAX_TOTAL_BYTES' in result['error']
    assert len(queries) == 3 and all(config.dry_run for _,config in queries)


def test_data_window_can_be_frozen_and_rejects_future(monkeypatch):
    monkeypatch.setenv('DATA_AS_OF_DATE','2026-01-02')
    assert fetch_data.window_end().isoformat()=='2026-01-02T00:00:00+00:00'
    future=datetime.datetime.now(datetime.timezone.utc).date()+datetime.timedelta(days=1)
    monkeypatch.setenv('DATA_AS_OF_DATE',future.isoformat())
    with pytest.raises(ValueError,match='future'):
        fetch_data.window_end()


def test_intents_pagination_rate_limit_cursor_and_no_double_counting(monkeypatch):
    yesterday = (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=1)).isoformat()
    first = [{'depositAddress':str(i),'depositMemo':None,'createdAt':yesterday,'status':'SUCCESS','amountInUsd':'1'} for i in range(1000)]
    calls, sleeps = [], []
    def get(url, **kwargs):
        calls.append(dict(kwargs['params']))
        return Mock(json=lambda:first if len(calls) == 1 else [],raise_for_status=lambda:None)
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr(fetch_data.time,'sleep',lambda seconds:sleeps.append(seconds))
    result = fetch_data.fetch_intents_api('TEST-ONLY')
    assert result['demo'] is False
    assert result['data']['daily_swap_volume_usd'][0]['volume_usd'] == 1000
    assert calls[1]['lastDepositAddress'] == '999'
    assert sleeps == [5]
    # A repeated page must fail, rather than doubling the daily total.
    monkeypatch.setattr(requests,'get',lambda *a,**k:Mock(json=lambda:first,raise_for_status=lambda:None))
    result = fetch_data.fetch_intents_api('TEST-ONLY')
    assert result['demo'] is True
    assert 'repeated' in result['error']
    assert result['data']['daily_swap_volume_usd'] == []
