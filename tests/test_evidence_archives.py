import datetime as dt
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import fetch_intents_history as history
from verify_evidence import verify_archives
from thesis_result import generate,canonical


def response(rows,status=200):
    return SimpleNamespace(status_code=status,headers={},json=lambda:rows,raise_for_status=lambda:None)


def row(identity,amount='1.25'):
    return {'depositAddress':str(identity),'depositMemo':None,'createdAt':'2026-01-01T12:00:00Z',
            'amountInUsd':amount,'nearTxHashes':['fixture-hash'],'status':'SUCCESS'}


@pytest.fixture
def window(tmp_path,monkeypatch):
    monkeypatch.setattr(history,'ROOT',tmp_path)
    start=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)
    end=start+dt.timedelta(days=1)
    folder=tmp_path/'data'/'intents-evidence'/'fixture-window'
    return start,end,folder,tmp_path


def test_archive_reproduces_exact_totals_and_reuses_completed_checkpoint(window):
    start,end,folder,root=window
    calls=[]
    def request(url,**kwargs):
        calls.append(kwargs['params'])
        return response([row('a'),row('b','2.50')])
    source=history.collect(start,end,folder,'TEST-ONLY',request=request)
    assert source['transaction_count']==2
    daily=source['data']['daily_swap_volume_usd'][0]
    assert daily['volume_usd']==3.75 and daily['volume_usd_decimal']=='3.75' and daily['swap_count']==2
    assert source['evidence_files'][0]['records']==2
    result={'evidence':{'raw_data':{'sources':[source]}}}
    assert verify_archives(result,root)==[{'source':'near-intents-explorer','pages':1,'records':2,'days':1,'verified':True}]
    restored=history.collect(start,end,folder,'TEST-ONLY',request=lambda *a,**k:pytest.fail('Completed checkpoint must not refetch'))
    assert restored==source
    assert len(calls)==1


def test_partial_window_resumes_without_losing_or_double_counting(window):
    start,end,folder,root=window
    params={'numberOfTransactions':1000,'statuses':'SUCCESS','direction':'next','startTimestamp':start.isoformat(),'endTimestamp':end.isoformat()}
    seed={'params':params,'rows':[row(i) for i in range(1000)]}
    with pytest.raises(ValueError,match='Page limit'):
        history.collect(start,end,folder,'TEST-ONLY',max_pages=1,seed=seed)
    checkpoint=json.loads((folder/'checkpoint.json').read_text())
    assert checkpoint['complete'] is False and checkpoint['records']==1000
    def request(url,**kwargs):
        assert kwargs['params']['lastDepositAddress']=='999'
        return response([row(1000,'0.01')])
    source=history.collect(start,end,folder,'TEST-ONLY',request=request)
    assert source['transaction_count']==1001
    assert source['data']['daily_swap_volume_usd'][0]['volume_usd_decimal']=='1250.01'
    assert verify_archives({'evidence':{'raw_data':{'sources':[source]}}},root)[0]['records']==1001


def test_archive_tamper_is_rejected_before_reuse_or_verification(window):
    start,end,folder,root=window
    source=history.collect(start,end,folder,'TEST-ONLY',request=lambda *a,**k:response([row(1)]))
    (folder/source['evidence_files'][0]['filename']).write_bytes(b'edited')
    with pytest.raises(ValueError,match='hash mismatch'):
        history.collect(start,end,folder,'TEST-ONLY',request=lambda *a,**k:pytest.fail('Do not silently replace evidence'))
    with pytest.raises(ValueError,match='hash or size differs'):
        verify_archives({'evidence':{'raw_data':{'sources':[source]}}},root)


def test_rate_limit_retry_does_not_create_partial_evidence(window):
    start,end,folder,_=window
    responses=iter([response([],429),response([row(1)])])
    sleeps=[]
    source=history.collect(start,end,folder,'TEST-ONLY',request=lambda *a,**k:next(responses),
                           sleep=lambda seconds:sleeps.append(seconds),clock=lambda:0)
    assert source['transaction_count']==1 and len(source['evidence_files'])==1
    assert sleeps and all(seconds>=5 for seconds in sleeps if seconds)


def test_changed_summary_cannot_pass_archive_verification(window):
    start,end,folder,root=window
    source=history.collect(start,end,folder,'TEST-ONLY',request=lambda *a,**k:response([row(1)]))
    source['data']['daily_swap_volume_usd'][0]['volume_usd_decimal']='999'
    with pytest.raises(ValueError,match='do not reproduce'):
        verify_archives({'evidence':{'raw_data':{'sources':[source]}}},root)


def test_generated_result_commits_complete_archive_and_rejects_changed_bytes(window):
    start,end,folder,root=window
    source=history.collect(start,end,folder,'TEST-ONLY',request=lambda *a,**k:response([row(i) for i in range(999)]))
    bundle={'demo':False,'sources':[source]}
    (root/'data'/'raw_fixture.json').write_text(canonical(bundle),encoding='utf-8')
    (root/'charts').mkdir()
    (root/'charts'/'manifest.json').write_text(canonical({'charts':[],'demo':False,'input_sha256':hashlib.sha256(canonical(bundle).encode()).hexdigest()}),encoding='utf-8')
    (root/'THESIS.md').write_text('Test fixture research only',encoding='utf-8')
    result=generate(root)
    assert result['evidence']['raw_data']['sources'][0]['transaction_count']==999
    assert len(canonical(result).encode('utf-8'))<10000
    (folder/source['evidence_files'][0]['filename']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='missing or differs'):
        generate(root)
