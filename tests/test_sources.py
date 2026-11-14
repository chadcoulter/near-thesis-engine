import datetime
import sys
import types
from unittest.mock import Mock

import pytest
import requests

import fetch_data


def test_bigquery_actual_tables_queries_and_date_serialization(monkeypatch):
    queries = []
    def query(sql):
        queries.append(sql)
        row = {'receiver_id':'fixture.near','call_count':2} if 'receipt_actions' in sql else {
            'block_date':datetime.date(2026,11,1),
            'daily_active_accounts' if 'DISTINCT' in sql else 'tx_count':3}
        return Mock(result=lambda:[row])
    bigquery = types.ModuleType('google.cloud.bigquery')
    bigquery.Client = lambda:Mock(query=query)
    google = types.ModuleType('google'); google.__path__ = []
    cloud = types.ModuleType('google.cloud'); cloud.__path__ = []; cloud.bigquery = bigquery
    monkeypatch.setitem(sys.modules,'google',google)
    monkeypatch.setitem(sys.modules,'google.cloud',cloud)
    monkeypatch.setitem(sys.modules,'google.cloud.bigquery',bigquery)
    bundle = fetch_data.fetch_bigquery()
    assert bundle['demo'] is False
    assert len(queries) == 3
    assert 'transactions`' in queries[0] and 'signer_account_id' in queries[0]
    assert 'receipt_actions`' in queries[2] and "action_kind = 'FUNCTION_CALL'" in queries[2]
    assert all('WHERE block_date >=' in sql for sql in queries)
    assert bundle['data']['daily_active_accounts'][0]['block_date'] == '2026-11-01'
    assert bundle['queries']['daily_active_accounts'] == queries[0]


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
