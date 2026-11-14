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


def fetch_bigquery() -> dict:
    """Query NEAR BigQuery public dataset for daily active accounts, tx counts, contract usage."""
    global IS_DEMO
    try:
        from google.cloud import bigquery
        client = bigquery.Client()
        queries = {
            "daily_active_accounts": f"""
                SELECT block_date, COUNT(DISTINCT signer_account_id) as daily_active_accounts
                FROM `{BIGQUERY_TABLE}`
                WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
                GROUP BY block_date ORDER BY block_date
            """,
            "transaction_counts": f"""
                SELECT block_date, COUNT(*) as tx_count
                FROM `{BIGQUERY_TABLE}`
                WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
                GROUP BY block_date ORDER BY block_date
            """,
            "contract_usage": f"""
                SELECT receipt_receiver_account_id AS receiver_id, COUNT(*) as call_count
                FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions`
                WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
                  AND action_kind = 'FUNCTION_CALL'
                GROUP BY receiver_id ORDER BY call_count DESC LIMIT 20
            """,
        }
        result = {}
        for name, q in queries.items():
            job = client.query(q)
            rows = [{k: v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v
                     for k, v in dict(r).items()} for r in job.result()]
            result[name] = rows
        return {"source": "near-bigquery", "fetched_at": _ts(), "demo": False, "queries": queries, "data": result}
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
        end = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        days = int(os.environ.get('INTENTS_WINDOW_DAYS', '30'))
        pages = int(os.environ.get('INTENTS_MAX_PAGES', '20'))
        if not 1 <= days <= 365 or not 1 <= pages <= 1000:
            raise ValueError('Invalid Intents window or page limit')
        start = end - datetime.timedelta(days=days)
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


if __name__ == "__main__":
    main()
