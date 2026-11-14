#!/usr/bin/env python3
"""
Seal thesis data, charts, and conclusions into the NEAR 231-gate sealed log.

Calls the deployed contract at sealed-log-2026.testnet:
  store_entry(agent_id, action_data) -> entry_id

Each sealed entry gets SUM/LINEAR/PROD mod 231 checksums over action_data.
Anyone can re-verify via verify_entry(entry_id, action_data) — any single-char
change breaks the checksums (tamper detected).

Writes scripts/seal_log.json with all entry IDs for the dashboard to reference.
"""
import json, os, shutil, subprocess, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = os.environ.get("SEALED_LOG_CONTRACT", "sealed-log-2026.testnet")
AGENT_ID = os.environ.get("SEALED_LOG_AGENT", "thesis-engine.testnet")
SEAL_LOG = ROOT / "scripts" / "seal_log.json"
MAX_PAYLOAD = 2000


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _check_near_cli():
    if shutil.which("near") is None:
        raise RuntimeError(
            "near-cli not found. Install: npm install -g near-cli\n"
            "Then login: near login\n"
            "Set SEALED_LOG_CONTRACT and SEALED_LOG_AGENT env vars if needed."
        )


def _near_call(method: str, args: dict) -> str:
    """Call a NEAR contract change method via near-cli. Returns raw stdout."""
    _check_near_cli()
    cmd = [
        "near", "call", CONTRACT, method,
        json.dumps(args, separators=(",", ":")),
        "--accountId", AGENT_ID,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"near call {method} failed: {result.stderr.strip()}")
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    if not lines:
        raise RuntimeError(f"near call {method} returned no output")
    return lines[-1]


def _near_view(method: str, args: dict) -> str:
    """Call a NEAR contract view method via near-cli. Returns raw stdout."""
    _check_near_cli()
    cmd = [
        "near", "view", CONTRACT, method,
        json.dumps(args, separators=(",", ":")),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"near view {method} failed: {result.stderr.strip()}")
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    if not lines:
        raise RuntimeError(f"near view {method} returned no output")
    return lines[-1]


def _truncate(label: str, payload: str) -> str:
    if len(payload) <= MAX_PAYLOAD:
        return payload
    # Truncate at a newline boundary if possible, else hard cut
    cut = payload[:MAX_PAYLOAD]
    nl = cut.rfind("\n")
    if nl > MAX_PAYLOAD * 0.8:
        cut = cut[:nl]
    return cut + f"\n...[truncated {len(payload) - len(cut)} chars]"


def seal(label: str, payload: str) -> dict:
    """Store one sealed entry; return the entry record."""
    payload = _truncate(label, payload)
    raw_id = _near_call("store_entry", {"agent_id": AGENT_ID, "action_data": payload})
    try:
        entry_id = int(raw_id)
    except ValueError:
        raise RuntimeError(f"store_entry returned non-numeric ID: {raw_id!r}")

    # Verify immediately — proves the entry was stored correctly
    intact_raw = _near_view("verify_entry", {"entry_id": entry_id, "action_data": payload})
    intact = intact_raw.strip().lower() == "true"
    return {
        "label": label,
        "entry_id": entry_id,
        "action_data": payload,
        "sealed_at": _now(),
        "verified_intact": intact,
    }


def main():
    # Collect everything worth sealing
    entries = []

    # 1. Latest raw data pull
    import glob
    data_files = sorted(glob.glob(str(ROOT / "data" / "raw_*.json")))
    if data_files:
        with open(data_files[-1]) as f:
            raw = f.read()
        entries.append(("thesis-data-pull", raw))

    # 2. Charts manifest
    manifest_path = ROOT / "charts" / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = f.read()
        entries.append(("thesis-charts-manifest", manifest))

    # 3. THESIS.md conclusion
    thesis_path = ROOT / "THESIS.md"
    if thesis_path.exists():
        with open(thesis_path) as f:
            thesis = f.read()
        entries.append(("thesis-conclusion", thesis))

    if not entries:
        print("Nothing to seal (no data, charts, or thesis found).")
        return

    results = []
    for label, payload in entries:
        try:
            rec = seal(label, payload)
            results.append(rec)
            print(json.dumps(rec, indent=2))
        except Exception as e:
            print(f"ERROR sealing {label}: {e}", file=sys.stderr)
            # Don't abort — seal what we can

    with open(SEAL_LOG, "w") as f:
        json.dump({"sealed_at": _now(), "entries": results}, f, indent=2)

    print(f"\nSealed {len(results)}/{len(entries)} entries -> {SEAL_LOG}")


if __name__ == "__main__":
    main()
