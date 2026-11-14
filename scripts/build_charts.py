#!/usr/bin/env python3
"""
Build charts from raw data.

One command that rebuilds every chart from raw data (per the organizer's thesis track prompt).
Reads the latest data/raw_*.json, generates PNG charts, writes charts/manifest.json.

Each chart entry includes the SQL query behind it and one plain-sentence takeaway,
so the dashboard can show "query + chart + what it shows" per the track prompt.

Takeaways are only generated when real data is present — demo mode (empty arrays)
produces no charts and no unverified claims.
"""
import json, glob, os, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CHARTS_DIR = ROOT / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.tmp' / 'matplotlib'))

BIGQUERY_TABLE = "bigquery-public-data.crypto_near_mainnet_us.transactions"

# Chart metadata: query behind the chart. Takeaway is computed from data, not hardcoded.
CHART_META = {
    "daily_active_accounts": {
        "query": f"SELECT block_date, COUNT(DISTINCT signer_account_id) as daily_active_accounts FROM `{BIGQUERY_TABLE}` WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) GROUP BY block_date ORDER BY block_date",
    },
    "transaction_counts": {
        "query": f"SELECT block_date, COUNT(*) as tx_count FROM `{BIGQUERY_TABLE}` WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) GROUP BY block_date ORDER BY block_date",
    },
    "contract_usage": {
        "query": "SELECT receipt_receiver_account_id AS receiver_id, COUNT(*) AS call_count FROM `bigquery-public-data.crypto_near_mainnet_us.receipt_actions` WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND action_kind = 'FUNCTION_CALL' GROUP BY receiver_id ORDER BY call_count DESC LIMIT 20",
    },
    "intents_swap_volume": {
        "query": "GET https://explorer.near-intents.org/api/v0/transactions; statuses=SUCCESS; sum amountInUsd by UTC createdAt date, complete bounded window only (requires partner JWT)",
    },
}

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:
    plt = None  # type: ignore[assignment]
    HAS_MPL = False


def _latest_raw() -> dict:
    files = sorted(glob.glob(str(DATA_DIR / "raw_*.json")))
    if not files:
        return {}
    with open(files[-1], encoding='utf-8') as f:
        return json.load(f)


def _save_chart(name: str, fig):
    path = CHARTS_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    import matplotlib.pyplot as _plt
    _plt.close(fig)
    return 'charts/' + path.name


def _takeaway(name: str, rows: list) -> str:
    """Compute a one-sentence takeaway from actual data — never hardcoded."""
    if not rows:
        return "No data available (demo mode — no credentials configured)."
    if name == "daily_active_accounts":
        first = rows[0]["daily_active_accounts"]
        last = rows[-1]["daily_active_accounts"]
        direction = "up" if last > first else "down" if last < first else "flat"
        return f"Daily active accounts moved {direction} over the period ({first} → {last}), based on {len(rows)} days of BigQuery data."
    if name == "transaction_counts":
        total = sum(r["tx_count"] for r in rows)
        avg = total / len(rows)
        return f"{len(rows)} days of transactions totaling {total:,} (avg {avg:,.0f}/day) from BigQuery."
    if name == "contract_usage":
        top = rows[0]
        return f"{top['receiver_id']} is the most-called contract with {top['call_count']} calls, based on {len(rows)} contracts from BigQuery."
    if name == "intents_swap_volume":
        total = sum(r["volume_usd"] for r in rows)
        return f"Intents swap volume totaled ${total:,.0f} over {len(rows)} days from the Intents Explorer API."
    return f"{len(rows)} rows of data from {name}."


def build(bundle: dict) -> dict:
    manifest = {"charts": [], "demo": bundle.get("demo", True), "built_at": bundle.get("fetched_at"),
                "input_sha256": hashlib.sha256(json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()}
    if not HAS_MPL:
        raise RuntimeError('matplotlib not installed; install requirements.txt before building charts')
    assert plt is not None  # HAS_MPL check above guarantees plt is bound

    sources = bundle.get("sources", [])

    for src in sources:
        data = src.get("data", {})
        source_name = src.get("source", "unknown")

        if "daily_active_accounts" in data:
            rows = data["daily_active_accounts"]
            if isinstance(rows, list) and rows:
                dates = [r["block_date"] for r in rows]
                vals = [r["daily_active_accounts"] for r in rows]
                fig = plt.figure(figsize=(8, 4))
                plt.plot(dates, vals, marker="o")
                plt.title(f"NEAR Daily Active Accounts ({source_name})")
                plt.xlabel("Date"); plt.ylabel("Accounts"); plt.xticks(rotation=45); plt.tight_layout()
                p = _save_chart("daily_active_accounts", fig)
                meta = CHART_META["daily_active_accounts"]
                manifest["charts"].append({
                    "name": "daily_active_accounts",
                    "path": p,
                    "source": source_name,
                    "query": src.get('queries', {}).get('daily_active_accounts', meta["query"]),
                    "takeaway": _takeaway("daily_active_accounts", rows),
                })

        if "transaction_counts" in data:
            rows = data["transaction_counts"]
            if isinstance(rows, list) and rows:
                dates = [r["block_date"] for r in rows]
                vals = [r["tx_count"] for r in rows]
                fig = plt.figure(figsize=(8, 4))
                plt.bar(dates, vals)
                plt.title(f"NEAR Transaction Counts ({source_name})")
                plt.xlabel("Date"); plt.ylabel("Transactions"); plt.xticks(rotation=45); plt.tight_layout()
                p = _save_chart("transaction_counts", fig)
                meta = CHART_META["transaction_counts"]
                manifest["charts"].append({
                    "name": "transaction_counts",
                    "path": p,
                    "source": source_name,
                    "query": src.get('queries', {}).get('transaction_counts', meta["query"]),
                    "takeaway": _takeaway("transaction_counts", rows),
                })

        if "contract_usage" in data:
            raw_rows = data["contract_usage"]
            if isinstance(raw_rows, list):
                rows = raw_rows[:10]
                if rows:
                    names = [r["receiver_id"] for r in rows]
                    vals = [r["call_count"] for r in rows]
                    fig = plt.figure(figsize=(8, 4))
                    plt.barh(names[::-1], vals[::-1])
                    plt.title(f"Top Contracts by Call Count ({source_name})")
                    plt.xlabel("Calls"); plt.tight_layout()
                    p = _save_chart("contract_usage", fig)
                    meta = CHART_META["contract_usage"]
                    manifest["charts"].append({
                        "name": "contract_usage",
                        "path": p,
                        "source": source_name,
                        "query": src.get('queries', {}).get('contract_usage', meta["query"]),
                        "takeaway": _takeaway("contract_usage", rows),
                    })

        if "daily_swap_volume_usd" in data:
            rows = data["daily_swap_volume_usd"]
            if isinstance(rows, list) and rows:
                dates = [r["date"] for r in rows]
                vals = [r["volume_usd"] for r in rows]
                fig = plt.figure(figsize=(8, 4))
                plt.plot(dates, vals, marker="s", color="green")
                plt.title(f"NEAR Intents Daily Swap Volume (USD) ({source_name})")
                plt.xlabel("Date"); plt.ylabel("Volume (USD)"); plt.xticks(rotation=45); plt.tight_layout()
                p = _save_chart("intents_swap_volume", fig)
                meta = CHART_META["intents_swap_volume"]
                manifest["charts"].append({
                    "name": "intents_swap_volume",
                    "path": p,
                    "source": source_name,
                    "query": src.get('query', meta["query"]),
                    "takeaway": _takeaway("intents_swap_volume", rows),
                })

    with open(CHARTS_DIR / "manifest.json", "w", encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main():
    bundle = _latest_raw()
    manifest = build(bundle)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
