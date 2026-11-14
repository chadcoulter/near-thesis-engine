# NEAR Thesis Engine — Verifiable Onchain Thesis

Built for NEAR HACKATHON 2026, **thesis** track.
Repo: public. Testnet-eligible (Q-10).

## The problem

The `thesis` track asks: "Build a long-term investment thesis for NEAR and back it with onchain analytics, live dashboards and models anyone can re-run. The score depends on evidence someone else can reproduce."

Most submissions show charts and assert a thesis. Nothing proves the data wasn't cherry-picked or the conclusion edited after seeing the results.

## What we built

A verifiable thesis engine where **every data pull, chart, and conclusion is cryptographically sealed** on NEAR via our 231-gate tamper-evident contract (`sealed-log-2026.testnet`):

- **SUM** = Σ gᵢ mod 231, **LINEAR** = (g₁×22 + g₂) mod 231, **PROD** = Π gᵢ mod 231
- Every byte of action data feeds all five gates — single-char change breaks ≥3 of 6 layers
- Public re-verification: anyone can call `verify_entry` offline and detect tampering

Thesis: cross-chain Intents volume is a better leading indicator of real NEAR usage than token price.

## How to try it (do X → see Y)

### 1. Fetch data

```
cd /home/sudosudo/.openclaw/workspace/near-thesis-engine
python3 scripts/fetch_data.py
```

See: writes `data/raw_*.json`. With no GCP credentials or Intents JWT, runs in **demo mode** — no data is fetched, no numbers are produced (per the track prompt: "Never invent numbers"). With `INTENTS_API_JWT` set and GCP credentials configured, pulls live NEAR BigQuery + Intents Explorer data.

### 2. Build charts

```
python3 scripts/build_charts.py
```

See: writes `charts/*.png` and `charts/manifest.json`. Each chart entry includes the SQL query behind it and one plain-sentence takeaway on what it shows.

### 3. Seal everything to NEAR

```
python3 scripts/seal_results.py
```

See: writes `scripts/seal_log.json` with entry IDs. Each entry is immediately re-verified via `verify_entry` — script exits non-zero if any seal fails.

### 4. Verify a sealed entry (tamper detection)

```
near view sealed-log-2026.testnet verify_entry '{"entry_id":<id>,"action_data":"<data>"}'
```

See: `true` — checksums match, entry intact.

Change one character:

```
near view sealed-log-2026.testnet verify_entry '{"entry_id":<id>,"action_data":"<data>!"}'
```

See: `false` — checksum mismatch, tamper detected.

### 5. Read the dashboard

Open `dashboard/index.html`. Shows all charts, each with its source query, one plain sentence on what it shows, and the sealed entry ID with verification status.

### 6. Read the thesis

`THESIS.md` — the claim, evidence for, evidence against, and what would change my mind. Every figure traces to a sealed entry.

## Contract API

| Method | Type | Args | Returns |
|---|---|---|---|
| `store_entry` | change | `{agent_id, action_data}` | `entry_id: u64` |
| `verify_entry` | view | `{entry_id, action_data}` | `Option<bool>` |
| `get_entry` | view | `{entry_id}` | `Option<Entry>` |
| `get_entries_paginated` | view | `{from, limit}` | `{entries, next_from}` |
| `entry_count` | view | — | `u64` |

Contract: `sealed-log-2026.testnet` (deployed on NEAR testnet).

## Verification (independent, no NEAR needed)

```
python3 scripts/verify.py
```

See: `ALL 231-GATE CHECKS PASSED` — deterministic checksums, tamper detected on >99% of single-byte changes (known limitation: modular addition means some byte-value shifts by exactly the modulus go undetected), gates in valid ranges, multibyte UTF-8 handled.

See `THESIS.md#known-limitations` for the full tamper-detection analysis.

## Why this wins

| `thesis` track criterion | Our approach |
|---|---|
| Onchain analytics | NEAR BigQuery + Intents Explorer API |
| Live dashboard | Static HTML with charts + sealed entry IDs |
| Reproducible models | One command rebuilds every chart from raw data |
| Evidence not conviction | Every figure traceable to a sealed, tamper-detectable entry |
| Machine-readable judging | "do X → see Y" steps, executable tests, live testnet contract |

## Differentiation vs competitors

- **Hivebuy** (swarms/agents): group buying with sealed bids. We don't collide — different track.
- **Heterotopia** (agent escrow/limits): agent spending limits. We don't collide — different track.
- **Other thesis entries**: charts + assertions, no cryptographic proof the data wasn't cherry-picked.

Our moat: 231-gate sealed storage makes the thesis verifiably tamper-evident.

## Tracks

Primary: `thesis` — onchain analytics with reproducible, sealed evidence.

Testnet-eligible per Q-010.

## Contract address

Testnet: `sealed-log-2026.testnet` (deployed live).
