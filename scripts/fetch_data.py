#!/usr/bin/env python3
"""
Fetch onchain data for the NEAR thesis engine.

Sources (per the organizer's thesis track prompt):
1. NEAR BigQuery public dataset (bigquery-public-data.crypto_near_mainnet_us)
   - daily active accounts, transaction counts, contract usage
   - filter on block_date to keep query costs down
2. NEAR Intents Explorer transaction API for bounded-window 1Click swap volume
   - needs JWT from partner dashboard (user puts it in .env)

Outputs: data/raw_*.json - one combined source bundle per run, timestamped.

Demo mode (no GCP credentials, no JWT): produces empty data arrays.
Per the track prompt: "Never invent numbers" — no figures are fabricated.
Clearly marked as demo in THESIS.md.
"""
import argparse
import json, os, subprocess, sys, datetime, time
from decimal import Decimal
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

BIGQUERY_TABLE = "bigquery-public-data.crypto_near_mainnet_us.transactions"
IS_DEMO = False


def _load_env():
    """Load .env file from project root if python-dotenv isn't installed."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        try:
            with open(env_path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val
        except Exception:
            pass  # .env parse failure is non-fatal; env vars take precedence


_load_env()


def _ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def window_end():
    today = datetime.datetime.now(datetime.timezone.utc).date()
    chosen = datetime.date.fromisoformat(os.environ.get('DATA_AS_OF_DATE') or today.isoformat())
    if chosen > today:
        raise ValueError('DATA_AS_OF_DATE cannot be in the future')
    return datetime.datetime.combine(chosen, datetime.time(), datetime.timezone.utc)


def fetch_bigquery() -> dict:
    """Query NEAR BigQuery public dataset for daily active accounts, tx counts, contract usage."""
    global IS_DEMO
    try:
        from google.cloud import bigquery
        project = os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('GCP_PROJECT_ID')
        client = bigquery.Client(project=project) if project else bigquery.Client()
        end = window_end().date()
        start = end - datetime.timedelta(days=30)
        contract_start = end - datetime.timedelta(days=7)
        queries = {
            "daily_active_accounts": f"""
                SELECT block_date, COUNT(DISTINCT signer_account_id) as daily_active_accounts
                FROM `{BIGQUERY_TABLE}`
                WHERE block_date >= @start_date AND block_date < @end_date
                GROUP BY block_date ORDER BY block_date
            """,
            "transaction_counts": f"""
                SELECT block_date, COUNT(*) as tx_count
                FROM `{BIGQUERY_TABLE}`
                WHERE block_date >= @start_date AND block_date < @end_date
                GROUP BY block_date ORDER BY block_date
            """,
            "contract_usage": f"""
                SELECT receipt_receiver_account_id AS receiver_id, COUNT(*) as call_count
                FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
                WHERE block_date >= @start_date AND block_date < @end_date
                  AND action_kind = 'FUNCTION_CALL'
                GROUP BY receiver_id ORDER BY call_count DESC LIMIT 20
            """,
        }
        per_query_limit = int(os.environ.get('BQ_MAX_BYTES_BILLED', '20000000000'))
        total_limit = int(os.environ.get('BQ_MAX_TOTAL_BYTES', '60000000000'))
        if per_query_limit <= 0 or total_limit <= 0:
            raise ValueError('BigQuery byte limits must be positive')
        parameters, estimates = {}, {}
        # Dry-run every query before submitting any billable query job.
        for name, q in queries.items():
            first = contract_start if name == 'contract_usage' else start
            parameters[name] = [bigquery.ScalarQueryParameter('start_date', 'DATE', first.isoformat()),
                                bigquery.ScalarQueryParameter('end_date', 'DATE', end.isoformat())]
            dry = client.query(q, job_config=bigquery.QueryJobConfig(
                dry_run=True, use_query_cache=False, query_parameters=parameters[name]))
            estimates[name] = dry.total_bytes_processed
            if type(estimates[name]) is not int or estimates[name] > per_query_limit:
                raise ValueError(f'BigQuery dry-run for {name} exceeds BQ_MAX_BYTES_BILLED; no data queries submitted')
        if sum(estimates.values()) > total_limit:
            raise ValueError('BigQuery dry-run exceeds BQ_MAX_TOTAL_BYTES; no data queries submitted')
        result, jobs = {}, {}
        for name, q in queries.items():
            job = client.query(q, job_config=bigquery.QueryJobConfig(
                maximum_bytes_billed=per_query_limit, query_parameters=parameters[name]))
            rows = [{k: v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v
                     for k, v in dict(r).items()} for r in job.result()]
            result[name] = rows
            jobs[name] = {'job_id': job.job_id, 'bytes_processed': job.total_bytes_processed,
                          'bytes_billed': job.total_bytes_billed, 'cache_hit': job.cache_hit}
        if any(not rows for rows in result.values()):
            raise ValueError('BigQuery returned an empty required metric in the completed-day window; check dataset freshness')
        return {"source": "near-bigquery", "fetched_at": _ts(), "demo": False, "queries": queries,
                'window': {'start_date': start.isoformat(), 'contract_start_date': contract_start.isoformat(),
                           'end_date_exclusive': end.isoformat(), 'timezone': 'UTC'},
                'query_project': client.project, 'dry_run_bytes': estimates, 'jobs': jobs, "data": result}
    except Exception as e:
        # No credentials — produce no data. Per the track prompt: "Never invent numbers."
        IS_DEMO = True
        return {
            "source": "near-bigquery",
            "fetched_at": _ts(),
            "demo": True,
            "error": str(e),
            "data": {
                "daily_active_accounts": [],
                "transaction_counts": [],
                "contract_usage": [],
            },
        }


def fetch_intents_api(jwt: str | None) -> dict:
    """Pull swap volume from NEAR Intents Explorer API."""
    global IS_DEMO
    if not jwt:
        IS_DEMO = True
        return {
            "source": "near-intents-explorer",
            "fetched_at": _ts(),
            "demo": True,
            "error": "No JWT provided (set INTENTS_API_JWT in .env)",
            "data": {
                "daily_swap_volume_usd": [],
            },
        }
    try:
        import requests
        headers = {"Authorization": f"Bearer {jwt}"}
        endpoint = 'https://explorer.near-intents.org/api/v0/transactions'
        end = window_end()
        days = int(os.environ.get('INTENTS_WINDOW_DAYS', '30'))
        pages = int(os.environ.get('INTENTS_MAX_PAGES', '20'))
        if not 1 <= days <= 365 or not 1 <= pages <= 1000:
            raise ValueError('Invalid Intents window or page limit')
        start = end - datetime.timedelta(days=days)
        if os.environ.get('INTENTS_EVIDENCE_MODE', 'inline') == 'archive':
            from fetch_intents_history import collect
            folder = DATA_DIR / 'intents-evidence' / f'{start.date().isoformat()}_{end.date().isoformat()}'
            return collect(start, end, folder, jwt, max_pages=pages)
        params = {'numberOfTransactions': 1000, 'statuses': 'SUCCESS', 'direction': 'next',
                  'startTimestamp': start.isoformat(), 'endTimestamp': end.isoformat()}
        initial_params = dict(params)
        records, seen = [], set()
        for page in range(pages):
            if page:
                time.sleep(5)  # Documented partner rate limit.
            r = requests.get(endpoint, headers=headers, params=params, timeout=30)
            r.raise_for_status()
            rows = r.json()
            if not isinstance(rows, list):
                raise ValueError('Explorer response must be a transaction array')
            for row in rows:
                identity = (row['depositAddress'], row.get('depositMemo'))
                if identity in seen:
                    raise ValueError('Explorer pagination repeated a transaction; refusing partial totals')
                seen.add(identity)
                timestamp = datetime.datetime.fromisoformat(row['createdAt'].replace('Z', '+00:00'))
                amount = Decimal(row['amountInUsd'])
                if row['status'] != 'SUCCESS' or not start <= timestamp < end or not amount.is_finite() or amount < 0:
                    raise ValueError('Invalid transaction in requested Explorer window')
                records.append({key: row.get(key) for key in ('depositAddress', 'depositMemo', 'createdAt', 'amountInUsd', 'nearTxHashes')})
            if len(rows) < 1000:
                break
            params.update(lastDepositAddress=rows[-1]['depositAddress'])
            if rows[-1].get('depositMemo') is not None:
                params['lastDepositMemo'] = rows[-1]['depositMemo']
            else:
                params.pop('lastDepositMemo', None)
        else:
            raise ValueError('Explorer page limit reached; no partial volume reported. Narrow INTENTS_WINDOW_DAYS or raise INTENTS_MAX_PAGES.')
        totals = {}
        for row in records:
            date = datetime.datetime.fromisoformat(row['createdAt'].replace('Z', '+00:00')).astimezone(datetime.timezone.utc).date().isoformat()
            totals[date] = totals.get(date, Decimal(0)) + Decimal(row['amountInUsd'])
        return {'source': 'near-intents-explorer', 'fetched_at': _ts(), 'demo': False,
                'query': f'GET {endpoint}; params={json.dumps(initial_params, sort_keys=True)}; sum amountInUsd by UTC createdAt date',
                'coverage': 'Complete returned SUCCESS swaps in bounded 1Click window; not all NEAR Intents activity. Days without returned swaps omitted.',
                'data': {'daily_swap_volume_usd': [{'date': day, 'volume_usd': float(total)} for day, total in sorted(totals.items())],
                         'transactions': records}}
    except Exception as e:
        IS_DEMO = True
        return {
            "source": "near-intents-explorer",
            "fetched_at": _ts(),
            "demo": True,
            "error": str(e),
            "data": {"daily_swap_volume_usd": []},
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-live', action='store_true', help='Exit nonzero unless both credentialed sources return observations')
    args = parser.parse_args()
    jwt = os.environ.get("INTENTS_API_JWT")

    bq = fetch_bigquery()
    intents = fetch_intents_api(jwt)

    demo = bq.get("demo", False) or intents.get("demo", False)

    bundle = {
        "fetched_at": _ts(),
        "demo": demo,
        "sources": [bq, intents],
    }

    out = DATA_DIR / f"raw_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out, "w", encoding='utf-8') as f:
        json.dump(bundle, f, indent=2)

    print(json.dumps({
        "status": "ok",
        "demo": demo,
        "bigquery_rows": {k: len(v) for k, v in bq.get("data", {}).items()},
        "intents_demo": intents.get("demo", False),
        "output": str(out),
    }, indent=2))
    if args.require_live and (demo or not intents.get('data', {}).get('daily_swap_volume_usd')):
        print('LIVE DATA REQUIRED: one or more sources failed or returned no observations; nothing was sealed.', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
