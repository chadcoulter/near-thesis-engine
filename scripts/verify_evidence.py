#!/usr/bin/env python3
"""Verify archived evidence bytes, unique swaps and exact decimal volume totals offline."""
import argparse
import datetime as dt
from decimal import Decimal
import gzip
import hashlib
import json
import sys
from pathlib import Path

from thesis_result import ROOT


def verify_archives(result,root=ROOT):
    checked=[]
    for source in result['evidence']['raw_data']['sources']:
        references=source.get('evidence_files',[])
        if not references: continue
        seen,totals,counts=set(),{},{}
        window=source['window']
        start=dt.datetime.fromisoformat(window['start'])
        end=dt.datetime.fromisoformat(window['end_exclusive'])
        for reference in references:
            path=(root/reference['path']).resolve()
            if not path.is_relative_to((root/'data'/'intents-evidence').resolve()):
                raise ValueError('Audit archive path escapes the evidence directory')
            with path.open('rb') as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if path.stat().st_size!=reference['bytes'] or digest!=reference['sha256']:
                raise ValueError(f'Archive hash or size differs: {reference["path"]}')
            content_hash=hashlib.sha256()
            record_count=0
            with gzip.open(path,'rb') as stream:
                for line in stream:
                    content_hash.update(line)
                    row=json.loads(line)
                    key=(row['depositAddress'],row.get('depositMemo'))
                    stamp=dt.datetime.fromisoformat(row['createdAt'].replace('Z','+00:00'))
                    amount=Decimal(row['amountInUsd'])
                    if key in seen or row['status']!='SUCCESS' or not start<=stamp<end or not amount.is_finite() or amount<0:
                        raise ValueError('Duplicate or invalid swap evidence')
                    seen.add(key)
                    day=stamp.astimezone(dt.timezone.utc).date().isoformat()
                    totals[day]=totals.get(day,Decimal(0))+amount
                    counts[day]=counts.get(day,0)+1
                    record_count+=1
            if content_hash.hexdigest()!=reference['content_sha256']:
                raise ValueError('Audit content hash differs')
            if record_count!=reference['records']:
                raise ValueError('Audit page record count differs')
        summaries=source['data']['daily_swap_volume_usd']
        if len(seen)!=source['transaction_count'] or len(summaries)!=len(totals):
            raise ValueError('Source record/day counts differ')
        for row in summaries:
            if (Decimal(row['volume_usd_decimal'])!=totals.get(row['date']) or
                    row['volume_usd']!=float(totals[row['date']]) or row['swap_count']!=counts[row['date']]):
                raise ValueError('Archived swaps do not reproduce reported daily volume')
        checked.append({'source':source['source'],'pages':len(references),'records':len(seen),'days':len(totals),'verified':True})
    return checked


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result',type=Path,default=ROOT/'artifacts'/'result.json')
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    result=json.loads(args.result.read_text(encoding='utf-8'))
    checked=verify_archives(result,args.root)
    print(json.dumps({'archives':checked,'verified':bool(checked),
                      'note':'All archive checks passed' if checked else 'No external audit archives were supplied'},indent=2))
    return 0 if checked else 1


if __name__=='__main__': sys.exit(main())
