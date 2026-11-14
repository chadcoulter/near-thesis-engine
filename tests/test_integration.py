import datetime
import hashlib
from http.server import HTTPServer
import json
from pathlib import Path
import subprocess
import threading
from unittest.mock import Mock

import pytest
import requests

import build_charts
import dashboard_server
import fetch_data
import seal_results
from thesis_result import canonical, generate
from verify import compute_checksums


@pytest.fixture
def research(tmp_path, monkeypatch):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'charts').mkdir()
    (tmp_path / 'THESIS.md').write_text('Hypothesis: Intents volume leads usage.\nCounterevidence remains necessary.', encoding='utf-8')
    bundle = {'demo': False, 'fetched_at': '2026-11-01T00:00:00Z', 'sources': [
        {'source':'TEST FIXTURE ONLY', 'data':{
            'daily_active_accounts':[{'block_date':'2026-10-31','daily_active_accounts':10}],
            'transaction_counts':[{'block_date':'2026-10-31','tx_count':20}],
            'contract_usage':[{'receiver_id':'fixture.near','call_count':3}],
            'daily_swap_volume_usd':[{'date':'2026-10-31','volume_usd':5.5}]}}]}
    (tmp_path / 'data' / 'raw_fixture.json').write_text(canonical(bundle), encoding='utf-8')
    monkeypatch.setattr(build_charts, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(build_charts, 'CHARTS_DIR', tmp_path / 'charts')
    build_charts.build(bundle)
    return tmp_path, bundle


def test_result_serialization_determinism_and_charts(research):
    root, bundle = research
    first = canonical(generate(root))
    build_charts.build(bundle)
    assert canonical(generate(root)) == first
    result = json.loads(first)
    assert result['demo'] is False
    assert len(result['chart_sha256']) == 4
    assert all(c['path'].startswith('charts/') for c in result['evidence']['chart_manifest']['charts'])
    for name, digest in result['chart_sha256'].items():
        assert hashlib.sha256((root/'charts'/name).read_bytes()).hexdigest() == digest


def test_stale_evidence_and_missing_asset_rejected(research):
    root, _ = research
    image = root / 'charts' / 'daily_active_accounts.png'
    image.unlink()
    with pytest.raises(ValueError, match='Missing chart'):
        generate(root)
    (root/'data'/'raw_fixture.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='does not match'):
        generate(root)


def test_no_credentials_no_invented_numbers(tmp_path):
    (tmp_path/'THESIS.md').write_text('Untested hypothesis', encoding='utf-8')
    result = generate(tmp_path)
    assert result['demo'] is True
    assert result['evidence']['raw_data']['sources'] == []
    assert result['chart_sha256'] == {}
    assert fetch_data.fetch_intents_api(None)['data']['daily_swap_volume_usd'] == []


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    entries = {}
    def near(method, args):
        if method == 'store_entry':
            entry_id = len(entries) + 1
            entries[entry_id] = {'entry_id':entry_id, **args, 'stored_by':'signer.testnet',
                                 'timestamp':1, 'checksums':compute_checksums(args['action_data'])}
            return {'entry_id':entry_id,'transaction_id':f'fixture-tx-{entry_id}'}
        if method == 'get_entry':
            return entries.get(args['entry_id'])
        if method == 'verify_entry':
            entry = entries.get(args['entry_id'])
            return None if entry is None else entry['checksums'] == compute_checksums(args['action_data'])
        if method == 'entry_count':
            return len(entries)
        if method == 'get_entries_paginated':
            batch = [entry for key, entry in entries.items() if key >= args['from']][:args['limit']]
            return {'entries':batch,'next_from':batch[-1]['entry_id'] + 1 if len(batch) == args['limit'] else None}
        raise AssertionError(method)
    monkeypatch.setattr(seal_results, 'near', near)
    monkeypatch.setattr(dashboard_server, 'near', near)
    log = tmp_path/'seal_log.json'
    monkeypatch.setattr(seal_results, 'SEAL_LOG', log)
    monkeypatch.setattr(dashboard_server, 'SEAL_LOG', log)
    return entries


def test_complete_seal_retrieve_verify_and_checksum_collision(ledger):
    payload = canonical({'schema':'near-thesis-result/v1','thesis':'x'*6000, 'unicode':'🚀'})
    record = seal_results.seal('thesis-result', payload)
    assert record['action_data'] == payload
    assert record['transaction_id'] == 'fixture-tx-1'
    assert record['verified_intact'] is True
    assert record['entry']['stored_by'] == 'signer.testnet'
    assert seal_results.verify(1, payload + '!')['verified_intact'] is False
    assert seal_results.verify(999, payload)['contract_verification'] is None
    seal_results.seal('collision', 'A')
    collision = seal_results.verify(2, 'W')
    assert collision['contract_verification'] is True
    assert collision['exact_match'] is False
    assert collision['verified_intact'] is False


def test_no_truncation_and_byte_limit(ledger):
    with pytest.raises(ValueError, match='exceeds'):
        seal_results.seal('large', '🚀' * (seal_results.MAX_PAYLOAD//4 + 1))
    assert ledger == {}


def test_preserves_transaction_when_verification_fails(ledger, monkeypatch):
    monkeypatch.setattr(seal_results, 'verify', Mock(side_effect=RuntimeError('RPC down')))
    with pytest.raises(RuntimeError, match='fixture-tx-1.*entry 1.*RPC down'):
        seal_results.seal('test','complete evidence')
    history = json.loads(seal_results.SEAL_LOG.read_text(encoding='utf-8'))
    assert history['entries'][0]['transaction_id'] == 'fixture-tx-1'
    assert history['entries'][0]['verified_intact'] is False
    assert history['entries'][0]['verification_error'] == 'RPC down'


def test_bridge_uses_stdin_and_reports_errors(monkeypatch):
    def run(command, **kwargs):
        assert command[0] == 'node'
        assert json.loads(kwargs['input']) == {'method':'verify_entry','args':{'entry_id':1,'action_data':'🚀'}}
        assert kwargs['encoding'] == 'utf-8'
        return subprocess.CompletedProcess(command,0,'{"result":null}','')
    monkeypatch.setattr(seal_results.subprocess,'run',run)
    assert seal_results.near('verify_entry',{'entry_id':1,'action_data':'🚀'}) is None
    monkeypatch.setattr(seal_results.subprocess,'run',lambda *a,**k: subprocess.CompletedProcess(a,1,'{"error":"contract missing"}',''))
    with pytest.raises(RuntimeError, match='contract missing'):
        seal_results.near('entry_count',{})
    monkeypatch.setattr(seal_results.subprocess,'run',Mock(side_effect=subprocess.TimeoutExpired('node',180)))
    with pytest.raises(RuntimeError, match='may have landed'):
        seal_results.near('entry_count',{})


def test_verification_rejects_non_boolean_response(monkeypatch):
    monkeypatch.setattr(seal_results,'near',lambda method,args: {'action_data':'x'} if method == 'get_entry' else 'true')
    with pytest.raises(RuntimeError,match='Invalid verification response'):
        seal_results.verify(1,'x')


@pytest.fixture
def server(research, ledger, monkeypatch):
    root, _ = research
    original_root = dashboard_server.ROOT
    monkeypatch.setattr(dashboard_server, 'generate', lambda: generate(root))
    # Keep actual HTML/JS; chart endpoint reads local fixture paths through a symlink-free copy.
    (root/'dashboard').mkdir()
    for name in ['index.html','app.js']:
        (root/'dashboard'/name).write_bytes((original_root/'dashboard'/name).read_bytes())
    monkeypatch.setattr(dashboard_server, 'ROOT', root)
    httpd = HTTPServer(('127.0.0.1',0), dashboard_server.Handler)
    thread = threading.Thread(target=httpd.serve_forever,daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_port}'
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_http_workflow_security_and_errors(server, monkeypatch):
    result = requests.post(server+'/api/generate', json={}).json()
    sealed = requests.post(server+'/api/seal', json={'action_data':result['action_data']})
    assert sealed.status_code == 200
    assert sealed.json()['verified_intact'] is True
    response = requests.post(server+'/api/verify',json={'entry_id':1,'action_data':result['action_data']})
    assert response.json()['entry']['action_data'] == result['action_data']
    assert requests.get(server+'/api/entries?from=1&limit=10').json()['count'] == 1
    for path in ['/.env','/scripts/seal_log.json','/package.json','/../.env']:
        assert requests.get(server+path).status_code == 404
    assert requests.post(server+'/api/seal',json={'action_data':result['action_data']},headers={'Origin':'https://attacker.example'}).status_code == 403
    assert requests.get(server+'/api/config',headers={'Host':'attacker.example'}).status_code == 403
    assert requests.post(server+'/api/verify',json={'entry_id':True,'action_data':'x'}).status_code == 400
    assert requests.get(server+'/api/entries?from=1&limit=0').status_code == 400
    monkeypatch.setattr(dashboard_server,'near',Mock(side_effect=RuntimeError('RPC unavailable')))
    assert requests.get(server+'/api/entries').status_code == 502


def test_intents_actual_endpoint_aggregation_and_failure(monkeypatch):
    yesterday = (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=1)).replace(hour=12).isoformat()
    rows = [{'depositAddress':f'fixture-{i}','depositMemo':None,'createdAt':yesterday,'status':'SUCCESS','amountInUsd':amount}
            for i, amount in enumerate(['1.25','2.50'])]
    def get(url, **kwargs):
        assert url == 'https://explorer.near-intents.org/api/v0/transactions'
        assert kwargs['params']['statuses'] == 'SUCCESS'
        assert kwargs['headers']['Authorization'] == 'Bearer TEST-ONLY'
        return Mock(json=lambda:rows,raise_for_status=lambda:None)
    monkeypatch.setattr(requests,'get',get)
    result = fetch_data.fetch_intents_api('TEST-ONLY')
    assert result['demo'] is False
    assert result['data']['daily_swap_volume_usd'][0]['volume_usd'] == 3.75
    monkeypatch.setattr(requests,'get',Mock(side_effect=RuntimeError('API down')))
    result = fetch_data.fetch_intents_api('TEST-ONLY')
    assert result['demo'] is True
    assert result['data']['daily_swap_volume_usd'] == []


def test_intents_refuses_partial_window(monkeypatch):
    yesterday = (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=1)).isoformat()
    rows = [{'depositAddress':str(i),'createdAt':yesterday,'status':'SUCCESS','amountInUsd':'1'} for i in range(1000)]
    monkeypatch.setenv('INTENTS_MAX_PAGES','1')
    monkeypatch.setattr(requests,'get',lambda *a,**k:Mock(json=lambda:rows,raise_for_status=lambda:None))
    result = fetch_data.fetch_intents_api('TEST-ONLY')
    assert result['demo'] is True
    assert 'page limit' in result['error']
    assert result['data']['daily_swap_volume_usd'] == []
