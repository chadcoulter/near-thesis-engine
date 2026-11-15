"""Fetch the fixed 90-day network and USD price comparison, without billing changes."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import requests
from fetch_data import _load_env
from google.cloud import bigquery

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/comparison-90d'

def main():
    _load_env()
    import os
    OUT.mkdir(exist_ok=True)
    start,end=dt.date(2026,8,16),dt.date(2026,11,14)
    client=bigquery.Client(project=os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('GCP_PROJECT_ID'))
    sql='''SELECT block_date, COUNT(*) AS tx_count,
    COUNT(DISTINCT signer_account_id) AS daily_active_accounts
    FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
    WHERE block_date >= @start_date AND block_date < @end_date
    GROUP BY block_date ORDER BY block_date'''
    params=[bigquery.ScalarQueryParameter('start_date','DATE',str(start)),bigquery.ScalarQueryParameter('end_date','DATE',str(end))]
    if not (OUT/'network.json').exists():
        estimate=client.query(sql,job_config=bigquery.QueryJobConfig(dry_run=True,use_query_cache=False,query_parameters=params)).total_bytes_processed
        if not isinstance(estimate,int) or estimate>20_000_000_000:
            raise ValueError(f'Dry run exceeds fixed 20GB cap: {estimate}')
        print('BigQuery dry run bytes:',estimate,flush=True)
        job=client.query(sql,job_config=bigquery.QueryJobConfig(maximum_bytes_billed=20_000_000_000,query_parameters=params))
        rows=[{k:v.isoformat() if isinstance(v,dt.date) else v for k,v in dict(row).items()} for row in job.result()]
        assert len(rows)==90
        bundle={'source':'NEAR BigQuery public transactions','query':sql,'start_inclusive':str(start),'end_exclusive':str(end),'fetched_at':dt.datetime.now(dt.timezone.utc).isoformat(),'job_id':job.job_id,'bytes_processed':job.total_bytes_processed,'dry_run_bytes':estimate,'rows':rows}
        (OUT/'network.json').write_text(json.dumps(bundle,indent=2),encoding='utf-8')
        print('Network rows:',len(rows),flush=True)
    endpoint='https://api.coingecko.com/api/v3/coins/near/market_chart/range'
    params={'vs_currency':'usd','from':int(dt.datetime.combine(start-dt.timedelta(days=1),dt.time(),dt.timezone.utc).timestamp()),'to':int(dt.datetime.combine(end,dt.time(),dt.timezone.utc).timestamp())}
    response=requests.get(endpoint,params=params,timeout=60)
    response.raise_for_status()
    payload=response.json()
    assert len(payload['prices'])>=90
    (OUT/'price-response.json').write_bytes(response.content)
    (OUT/'price-provenance.json').write_text(json.dumps({'source':'CoinGecko NEAR/USD aggregate reference price','endpoint':endpoint,'params':params,'fetched_at':dt.datetime.now(dt.timezone.utc).isoformat(),'response_sha256':hashlib.sha256(response.content).hexdigest(),'documentation':'https://docs.coingecko.com/v3.0.1/reference/coins-id-market-chart-range','note':'Daily 00:00 UTC observations. Price for day t is the observation exactly at t+1 midnight, available by the forecast cutoff. No daily OHLC close is claimed.'},indent=2),encoding='utf-8')
    print('Price points:',len(payload['prices']),flush=True)

if __name__=='__main__': main()
