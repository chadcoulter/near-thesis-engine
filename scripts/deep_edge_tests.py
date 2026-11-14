#!/usr/bin/env python3
"""Deep edge-case tests for the thesis engine."""
import json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

errors = []

def check(name, cond, detail=""):
    if cond:
        print(f"  PASS {name}")
    else:
        print(f"  FAIL {name} {detail}")
        errors.append(name)

# ── Test 1: fetch_data.py .env loading ──────────────────────────────
print("\n=== fetch_data.py .env loading ===")
import fetch_data
# .env loading happens at import time; verify no crash
check("imports without crash", True)

# ── Test 2: fetch_data.py empty data in demo mode ───────────────────
print("\n=== fetch_data.py demo mode ===")
os.environ.pop("INTENTS_API_JWT", None)
# Reload to reset IS_DEMO
import importlib
importlib.reload(fetch_data)
# Call the fetch functions to trigger IS_DEMO setting
fetch_data.fetch_bigquery()
fetch_data.fetch_intents_api(None)
check("demo mode is True", fetch_data.IS_DEMO == True)

# ── Test 3: build_charts.py with empty data ─────────────────────────
print("\n=== build_charts.py empty data ===")
import build_charts
chart_scratch = tempfile.TemporaryDirectory(prefix='thesis-edge-charts-')
build_charts.CHARTS_DIR = Path(chart_scratch.name)
empty_bundle = {"demo": True, "fetched_at": "2026-01-01T00:00:00+00:00", "sources": []}
manifest = build_charts.build(empty_bundle)
check("empty bundle returns manifest", "charts" in manifest)
check("no charts from empty data", len(manifest["charts"]) == 0)
check("demo flag preserved", manifest["demo"] == True)

# ── Test 4: build_charts.py with malformed data ─────────────────────
print("\n=== build_charts.py malformed data ===")
malformed_bundle = {
    "demo": False,
    "fetched_at": "2026-01-01T00:00:00+00:00",
    "sources": [
        {"source": "near-bigquery", "data": {"daily_active_accounts": None}},
        {"source": "near-intents-explorer", "data": {"daily_swap_volume_usd": "not a list"}},
    ],
}
try:
    manifest2 = build_charts.build(malformed_bundle)
    check("malformed data doesn't crash", True)
    check("no charts from None data", len(manifest2["charts"]) == 0)
except Exception as e:
    check("malformed data doesn't crash", False, str(e))

# ── Test 5: build_charts.py with valid data and takeaway correctness ─
print("\n=== build_charts.py valid data takeaways ===")
valid_bundle = {
    "demo": False,
    "fetched_at": "2026-01-01T00:00:00+00:00",
    "sources": [
        {
            "source": "near-bigquery",
            "data": {
                "daily_active_accounts": [
                    {"block_date": "2026-11-01", "daily_active_accounts": 1000},
                    {"block_date": "2026-11-02", "daily_active_accounts": 1200},
                ],
                "transaction_counts": [
                    {"block_date": "2026-11-01", "tx_count": 50000},
                    {"block_date": "2026-11-02", "tx_count": 52000},
                ],
                "contract_usage": [
                    {"receiver_id": "rhea.finance", "call_count": 8420},
                    {"receiver_id": "ref-finance.near", "call_count": 6210},
                ],
            },
        },
        {
            "source": "near-intents-explorer",
            "data": {
                "daily_swap_volume_usd": [
                    {"date": "2026-11-01", "volume_usd": 2450000},
                    {"date": "2026-11-02", "volume_usd": 2890000},
                ],
            },
        },
    ],
}
manifest3 = build_charts.build(valid_bundle)
check("4 charts generated", len(manifest3["charts"]) == 4)
for c in manifest3["charts"]:
    check(f"chart {c['name']} has takeaway", bool(c.get("takeaway")))
    check(f"chart {c['name']} has query", bool(c.get("query")))
    check(f"chart {c['name']} takeaway not hardcoded", "rhea.finance" not in c.get("takeaway", "") or c["name"] == "contract_usage")

# ── Test 6: seal_results.py truncation ──────────────────────────────
print("\n=== seal_results.py full payload preservation ===")
import seal_results
from thesis_result import canonical
long_payload = "🚀" * 5000 + "\ncomplete evidence"
check("long Unicode evidence preserved through serialization", json.loads(canonical(long_payload)) == long_payload)
try:
    seal_results.seal('oversize-test', '🚀' * (seal_results.MAX_PAYLOAD // 4 + 1))
    check('oversized evidence rejected before sending', False)
except ValueError:
    check('oversized evidence rejected before sending', True)

# ── Test 7: verify.py edge cases ────────────────────────────────────
print("\n=== verify.py edge cases ===")
import verify

# Empty string
c_empty = verify.compute_checksums("")
check("empty string checksums in range", all(0 <= v < verify.MOD for v in c_empty.values()))

# Unicode
c_uni = verify.compute_checksums("日本語テスト 🚀")
c_uni2 = verify.compute_checksums("日本語テスト 🚀")
check("unicode deterministic", c_uni == c_uni2)
c_uni_t = verify.compute_checksums("日本語テスト 🚀!")
check("unicode tamper detected", c_uni != c_uni_t)

# Very long input
long_input = "z" * 1000000
c_long = verify.compute_checksums(long_input)
check("1M-char input gates in range", all(0 <= x < verify.MOD for x in c_long.values()))

# 1000 diverse inputs should produce unique checksums (tamper detection property)
import hashlib
samples = [hashlib.sha256(f"unique-entry-{i}-random-salt-xyz".encode()).hexdigest() for i in range(1000)]
checksums = [verify.compute_checksums(s) for s in samples]
unique = len({(c["sum"], c["linear"], c["prod"]) for c in checksums})
check(f"1000 diverse inputs produce {unique} unique signatures (should be > 900)", unique > 900, f"got {unique}")

# Single-byte change detection rate (tamper property)
# NOTE: 231-gate uses modular addition, so adding the modulus (22 or 231) to a
# byte at a position that maps to a given slot does NOT change that slot's gate.
# E.g. position 0 -> slot 0 (bound 22): 'A'(65) and 'W'(87) both give 65%22=87%22=21.
# This means some single-byte changes are NOT detected. The gate is designed for
# detecting common tampering (edits, insertions, deletions), not for cryptographic
# collision resistance. Documented as a known limitation.
base = "tamper-measurement-data"
c_base = verify.compute_checksums(base)
total_tests = 0
detected = 0
for i in range(len(base)):
    for replacement in range(256):
        replacement_char = chr(replacement)
        if replacement_char == base[i]:
            continue
        mutated = base[:i] + replacement_char + base[i+1:]
        c_mut = verify.compute_checksums(mutated)
        total_tests += 1
        if c_base != c_mut:
            detected += 1
detection_rate = detected / total_tests if total_tests > 0 else 0
check(f"single-byte change detection rate: {detected}/{total_tests} = {detection_rate:.1%}", detection_rate > 0.95, f"got {detection_rate:.1%}")

# ── Test 8: THESIS.md has no invented numbers ───────────────────────
print("\n=== THESIS.md no invented numbers ===")
thesis_path = ROOT / "THESIS.md"
with open(thesis_path, encoding='utf-8') as f:
    thesis = f.read()
# Check for the specific invented numbers from before
check("no '1,240 → 1,420' invented figure", "1,240" not in thesis)
check("no '48,200 → 52,800' invented figure", "48,200" not in thesis)
check("no '$2.45M → $2.98M' invented figure", "$2.45M" not in thesis)
check("no '8,420 calls' invented figure", "8,420 calls" not in thesis)
check("has 'could NOT be computed' section", "could NOT be computed" in thesis)

# ── Test 9: Dashboard XSS escaping ──────────────────────────────────
print("\n=== dashboard XSS escaping ===")
dashboard_path = ROOT / "dashboard" / "index.html"
with open(dashboard_path, encoding='utf-8') as f:
    dashboard = f.read()
app = (ROOT / 'dashboard' / 'app.js').read_text(encoding='utf-8')
check('dashboard renders dynamic text without HTML interpolation', 'textContent' in app and 'innerHTML' not in app)
check('dashboard loads external app script', '/dashboard/app.js' in dashboard)
# Browser execution and malicious result rendering are tested in tests/test_dashboard.py.

print()
if errors:
    print(f"{len(errors)} TEST(S) FAILED: {errors}")
    sys.exit(1)
print("ALL DEEP EDGE-CASE TESTS PASSED")
chart_scratch.cleanup()
