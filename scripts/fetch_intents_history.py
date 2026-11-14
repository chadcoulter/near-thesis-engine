#!/usr/bin/env python3
"""Resumable complete-window Explorer pull with hash-addressed audit pages."""
import argparse
import datetime as dt
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

import requests

from fetch_data import _load_env
from thesis_result import ROOT, canonical

ENDPOINT='https://explorer.near-intents.org/api/v0/transactions'
FIELDS=('depositAddress','depositMemo','createdAt','amountInUsd','nearTxHashes','status')


def save_state(folder,state):
    temporary=folder/'checkpoint.tmp'
    temporary.write_text(canonical(state),encoding='utf-8')
    temporary.replace(folder/'checkpoint.json')


def combine_pages(folder,state):
    """Hash complete records in portable audit parts, each normally under eight MB."""
    if state.get('archives'):
        for reference in state['archives']:
            path=folder/reference['filename']
            with path.open('rb') as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if digest!=reference['sha256'] or path.stat().st_size!=reference['bytes']:
                raise ValueError('Final audit archive hash mismatch')
        return state['archives']
    groups=[]
    group=[]
    size=0
    for page in state['pages']:
        if group and size+page['bytes']>8_000_000:
            groups.append(group); group=[]; size=0
        group.append(page); size+=page['bytes']
    if group: groups.append(group)
    references=[]
    for index,pages in enumerate(groups,1):
        path=folder/f'transactions-part-{index:03d}.jsonl.gz'
        compressed_hash,content_hash=hashlib.sha256(),hashlib.sha256()
        size=records=0
        temporary=path.with_suffix('.tmp')
        with temporary.open('wb') as output:
            for page in pages:
                compressed=(folder/page['filename']).read_bytes()
                if hashlib.sha256(compressed).hexdigest()!=page['sha256']:
                    raise ValueError('Audit page changed while combining')
                output.write(compressed)
                compressed_hash.update(compressed)
                content_hash.update(gzip.decompress(compressed))
                size+=len(compressed); records+=page['records']
        temporary.replace(path)
        references.append({'filename':path.name,'sha256':compressed_hash.hexdigest(),'content_sha256':content_hash.hexdigest(),
                           'bytes':size,'records':records,'format':'gzip JSON Lines (concatenated members)'})
    state['archives']=references
    save_state(folder,state)
    return references


def collect(start,end,folder,token,max_pages=1000,seed=None,request=requests.get,sleep=time.sleep,clock=time.monotonic):
    if start.tzinfo is None or end.tzinfo is None or not start < end:
        raise ValueError('An ordered timezone-aware window is required')
    if end > dt.datetime.now(dt.timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0):
        raise ValueError('Only completed UTC days can be collected')
    if not token:
        raise ValueError('INTENTS_API_JWT is required')
    params={'numberOfTransactions':1000,'statuses':'SUCCESS','direction':'next',
            'startTimestamp':start.isoformat(),'endTimestamp':end.isoformat()}
    folder.mkdir(parents=True,exist_ok=True)
    checkpoint=folder/'checkpoint.json'
    state=json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {
        'schema':'intents-explorer-archive/v1','endpoint':ENDPOINT,'params':params,'pages':[],'complete':False}
    if state['params'] != params or state['endpoint'] != ENDPOINT:
        raise ValueError('Checkpoint window or endpoint differs')
    seen,totals,counts=set(),{},{}

    def validate(rows):
        projected=[]
        local=set()
        for row in rows:
            identity=(row['depositAddress'],row.get('depositMemo'))
            if identity in seen or identity in local:
                raise ValueError('Duplicate transaction across Explorer pages; refusing partial totals')
            stamp=dt.datetime.fromisoformat(row['createdAt'].replace('Z','+00:00'))
            amount=Decimal(row['amountInUsd'])
            if row.get('status') != 'SUCCESS' or not start <= stamp < end or not amount.is_finite() or amount < 0:
                raise ValueError('Invalid transaction in requested complete window')
            local.add(identity)
            projected.append({field:row.get(field) for field in FIELDS})
        return projected

    def include(rows):
        for row in rows:
            seen.add((row['depositAddress'],row.get('depositMemo')))
            day=dt.datetime.fromisoformat(row['createdAt'].replace('Z','+00:00')).astimezone(dt.timezone.utc).date().isoformat()
            totals[day]=totals.get(day,Decimal(0))+Decimal(row['amountInUsd'])
            counts[day]=counts.get(day,0)+1

    last=None
    for page in state['pages']:
        path=folder/page['filename']
        compressed=path.read_bytes()
        if hashlib.sha256(compressed).hexdigest() != page['sha256']:
            raise ValueError('Checkpoint audit page hash mismatch')
        plain=gzip.decompress(compressed)
        if hashlib.sha256(plain).hexdigest() != page['content_sha256']:
            raise ValueError('Checkpoint audit content hash mismatch')
        rows=[json.loads(line) for line in plain.decode('utf-8').splitlines()]
        if len(rows) != page['records']:
            raise ValueError('Checkpoint record count mismatch')
        rows=validate(rows); include(rows)
        if rows: last=rows[-1]
    last_request=None
    while not state['complete']:
        if len(state['pages']) >= max_pages:
            raise ValueError('Page limit reached; checkpoint retained, no complete volume reported')
        query=dict(params)
        if last is not None:
            query['lastDepositAddress']=last['depositAddress']
            if last.get('depositMemo') is not None:
                query['lastDepositMemo']=last['depositMemo']
        if not state['pages'] and seed is not None:
            if seed['params'] != params:
                raise ValueError('Seed page has a different window')
            raw=seed['rows']
            seed=None
        else:
            for attempt in range(4):
                if last_request is not None:
                    sleep(max(0,5-(clock()-last_request)))
                last_request=clock()
                try:
                    response=request(ENDPOINT,headers={'Authorization':'Bearer '+token},params=query,timeout=60)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 3:
                            response.raise_for_status()
                        retry=response.headers.get('Retry-After','5')
                        sleep(max(5,float(retry) if retry.replace('.','',1).isdigit() else 5))
                        continue
                    response.raise_for_status()
                    raw=response.json()
                    break
                except requests.RequestException:
                    if attempt == 3: raise
                    sleep(5)
            else: raise RuntimeError('Explorer request failed')
        if not isinstance(raw,list) or len(raw)>1000:
            raise ValueError('Invalid Explorer page shape')
        rows=validate(raw)
        plain=('\n'.join(canonical(row) for row in rows)+ ('\n' if rows else '')).encode('utf-8')
        compressed=gzip.compress(plain,mtime=0)
        filename=f'page-{len(state["pages"])+1:06d}.jsonl.gz'
        (folder/filename).write_bytes(compressed)
        include(rows)
        if rows: last=rows[-1]
        state['pages'].append({'filename':filename,'sha256':hashlib.sha256(compressed).hexdigest(),
                               'content_sha256':hashlib.sha256(plain).hexdigest(),'bytes':len(compressed),'records':len(rows)})
        state['complete']=len(rows)<1000
        state['records']=len(seen)
        state['updated_at']=dt.datetime.now(dt.timezone.utc).isoformat()
        state['oldest_created_at']=last['createdAt'] if last else None
        save_state(folder,state)
        if len(state['pages'])%5==0 or state['complete']:
            print(canonical({'pages':len(state['pages']),'records':len(seen),'oldest':state['oldest_created_at'],'complete':state['complete']}),flush=True)
    archives=combine_pages(folder,state)
    references=[{**archive,'path':(folder/archive['filename']).relative_to(ROOT).as_posix()} for archive in archives]
    return {'source':'near-intents-explorer','demo':False,'fetched_at':state['updated_at'],
            'window':{'start':start.isoformat(),'end_exclusive':end.isoformat(),'timezone':'UTC'},
            'query':(f'GET {ENDPOINT}; params={canonical(state["collection_provenance"]["original_params"])}; locally restrict to {start.isoformat()} <= createdAt < {end.isoformat()}; sum amountInUsd by UTC date'
                     if state.get('collection_provenance') else f'GET {ENDPOINT}; params={canonical(params)}; sum amountInUsd by UTC createdAt date'),
            'collection_provenance':state.get('collection_provenance',{'method':'direct complete-window cursor pagination'}),
            'coverage':'All returned SUCCESS 1Click swaps in the complete bounded window. Not all NEAR Intents activity; days with no returned swaps omitted.',
            'snapshot_consistency':'Cursor pagination is not an atomic database snapshot; late settlements or backfills can change future reruns.',
            'audit_storage':'Complete contributing records in gzip JSONL pages; each archive and uncompressed content are SHA-256 committed. No transaction records are truncated.',
            'archive_schema':list(FIELDS),'evidence_files':references,'transaction_count':len(seen),'retrieved_pages':len(state['pages']),
            'data':{'daily_swap_volume_usd':[{'date':day,'volume_usd':float(total),'volume_usd_decimal':format(total,'f'),'swap_count':counts[day]} for day,total in sorted(totals.items())]}}


def main():
    _load_env()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-date',required=True)
    parser.add_argument('--end-date',required=True)
    parser.add_argument('--max-pages',type=int,default=1000)
    parser.add_argument('--seed-page',type=Path)
    args=parser.parse_args()
    start=dt.datetime.combine(dt.date.fromisoformat(args.start_date),dt.time(),dt.timezone.utc)
    end=dt.datetime.combine(dt.date.fromisoformat(args.end_date),dt.time(),dt.timezone.utc)
    folder=ROOT/'data'/'intents-evidence'/f'{args.start_date}_{args.end_date}'
    seed=json.loads(args.seed_page.read_text(encoding='utf-8')) if args.seed_page else None
    result=collect(start,end,folder,os.environ.get('INTENTS_API_JWT'),args.max_pages,seed)
    (folder/'source.json').write_text(canonical(result),encoding='utf-8')
    print(canonical({'complete':True,'source_file':str(folder/'source.json'),'records':result['transaction_count'],'days':len(result['data']['daily_swap_volume_usd'])}))


if __name__=='__main__':
    main()
