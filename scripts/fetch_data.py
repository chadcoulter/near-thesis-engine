#!/usr/bin/env python3
"""
Fetch onchain data for the NEAR thesis engine.

Sources (per the organizer's thesis track prompt):
1. NEAR BigQuery public dataset (bigquery-public-data.crypto_near_mainnet_us)
   - daily active accounts, transaction counts, contract usage
   - filter on block_date to keep query costs down
2. NEAR Intents Explorer API for swap volume
   - needs JWT from partner dashboard (user puts it in .env)

Outputs: data/raw_*.json — one file per source, timestamped.

Demo mode (no GCP credentials, no JWT): produces empty data arrays.
Per the track prompt: "Never invent numbers" — no figures are fabricated.
Clearly marked as demo in THESIS.md.
"""
import json, os, subprocess, sys, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

BIGQUERY_TABLE = "bigquery-public-data.crypto_near_mainnet_us"
IS_DEMO = False


def _load_env():
    """Load .env file from project root if python-dotenv isn't installed."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        try:
            with open(env_path) as f:
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
                SELECT block_date, COUNT(DISTINCT signer_id) as daily_active_accounts
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
                SELECT receiver_id, COUNT(*) as call_count
                FROM `{BIGQUERY_TABLE}`
                WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
                  AND receiver_id IS NOT NULL
                GROUP BY receiver_id ORDER BY call_count DESC LIMIT 20
            """,
        }
        result = {}
        for name, q in queries.items():
            job = client.query(q)
            rows = [dict(r) for r in job.result()]
            result[name] = rows
        return {"source": "near-bigquery", "fetched_at": _ts(), "demo": False, "data": result}
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
        r = requests.get(
            "https://api.near-intents.org/v1/explorer/swap-volume",
            headers=headers, timeout=30,
        )
        r.raise_for_status()
        return {"source": "near-intents-explorer", "fetched_at": _ts(), "demo": False, "data": r.json()}
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
    with open(out, "w") as f:
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
