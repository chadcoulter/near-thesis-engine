# NEAR Thesis — Cross-Chain Intents Volume as Leading Indicator

Built for NEAR HACKATHON 2026, **thesis** track. Testnet-eligible (Q-010).

## The claim

**Cross-chain swap volume through NEAR Intents is a better leading indicator of real network usage than NEAR token price.**

Token price is noisy, forward-looking, and easily manipulated. Cross-chain volume through NEAR Intents measures actual economic activity — users and agents moving value across chains through NEAR's settlement layer. If Intents volume rises while price is flat, real usage is growing ahead of price discovery.

## Data sources (per track prompt)

| Source | Table / Endpoint | SQL query | block_date filter |
|---|---|---|---|
| NEAR BigQuery public dataset | `bigquery-public-data.crypto_near_mainnet_us.transactions` | `SELECT block_date, COUNT(DISTINCT signer_account_id) as daily_active_accounts FROM \`bigquery-public-data.crypto_near_mainnet_us.transactions\` WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) GROUP BY block_date ORDER BY block_date` | Yes — `block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)` |
| NEAR BigQuery public dataset | `bigquery-public-data.crypto_near_mainnet_us.transactions` | `SELECT block_date, COUNT(*) as tx_count FROM \`bigquery-public-data.crypto_near_mainnet_us.transactions\` WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) GROUP BY block_date ORDER BY block_date` | Yes — `block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)` |
| NEAR BigQuery public dataset | `bigquery-public-data.crypto_near_mainnet_us.receipt_actions` | `SELECT receipt_receiver_account_id AS receiver_id, COUNT(*) AS call_count FROM \`bigquery-public-data.crypto_near_mainnet_us.receipt_actions\` WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) AND action_kind = 'FUNCTION_CALL' GROUP BY receiver_id ORDER BY call_count DESC LIMIT 20` | Yes - 7 days |
| NEAR Intents Explorer API | `GET https://explorer.near-intents.org/api/v0/transactions` | N/A (API pull, not SQL) | N/A |

Sample query (daily active accounts):

```sql
SELECT block_date, COUNT(DISTINCT signer_account_id) as daily_active_accounts
FROM `bigquery-public-data.crypto_near_mainnet_us.transactions`
WHERE block_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY block_date
ORDER BY block_date
```

## Metrics that could NOT be computed

This run executed in **demo mode** because no GCP credentials or Intents API JWT were available. Per the track prompt ("Never invent numbers"), **no figures are reported** for:

- Daily active accounts (BigQuery query not run — no credentials)
- Transaction counts (BigQuery query not run — no credentials)
- Contract usage / top contracts (BigQuery query not run — no credentials)
- Intents swap volume (API not called — no JWT)

To compute these, set `INTENTS_API_JWT` (from https://partners.near-intents.org) and GCP credentials, then run `python3 scripts/fetch_data.py`. Until then, THESIS.md intentionally contains **no numbers**.

## Evidence FOR the claim

None reported yet — no live data has been fetched. The hypothesis is plausible on first principles (cross-chain settlement volume measures actual economic activity; price is forward-looking and manipulable) but untested against data.

## Evidence AGAINST the claim

- **Correlation vs causation**: Intents volume could rise because of a single large airdrop or incentive program, not organic usage. We don't distinguish organic vs incentivized volume.
- **Sample size**: 30 days of daily data is short for a "leading indicator" claim. Needs 90+ days to establish predictive power.
- **Price leads volume in bull markets**: In strong uptrends, price often rises first and volume follows — the reverse of our claim. We haven't tested bear-market periods.
- **Data freshness**: BigQuery has ingestion lag; Intents API may not capture all cross-chain routes (some settle off-explorer).

## What would change my mind

- **Intents volume falls 30%+ while daily active accounts rise** → volume is not tracking real usage; claim weakened.
- **Intents volume rises 50%+ in a 14-day window with no price move** → volume is leading price; claim strengthened.
- **90+ day Granger causality test shows Intents volume predicts transaction counts (p < 0.05)** → claim confirmed with statistical rigor.
- **Granger test shows price predicts volume, not vice versa** → claim reversed; price is the leading indicator.

## Verification

Generate a canonical result containing this thesis, raw evidence, chart manifest and chart SHA-256 identifiers, then record the complete result at `redsigma.testnet` on NEAR Testnet. The original SUM/LINEAR/PRODUCT mod 231 algorithm remains unchanged. The application requires both a true contract verification response and exact equality between the candidate and retrieved `action_data`.

```sh
python scripts/seal_results.py --prepare
python scripts/testnet_smoke.py
# After contract deployment and local signer configuration:
python scripts/seal_results.py
python scripts/seal_results.py --verify ENTRY_ID
```

At the November 14, 2026 integration check, the account existed but had no contract code. No successful on-chain seal is claimed until deployment, signing and retrieval have actually completed. See README.md for the exact deployment/signing steps and CONTRACT_INTEGRATION.md for the inspected ABI.

## Dashboard

Run `python scripts/dashboard_server.py` and open `http://127.0.0.1:8000`. Generate or load a result; inspect its supporting evidence; submit it with a locally configured Testnet signer; inspect the transaction identifier; retrieve the entry; and verify the exact content. Missing data, missing entries, mismatches and RPC failures are displayed separately.

The chart calculations remain descriptive. The Explorer adapter aggregates complete bounded windows of successful **1Click** swaps, not all Intents activity. It omits days without returned transactions and refuses partial totals when pagination fails or reaches its limit. Source errors remain visible in the result. The live credentialed data paths require GCP and partner API authorization; offline test fixtures are not research evidence.

## Known Limitations

**231-gate tamper detection is not cryptographic collision resistance.** The gate derivation uses modular addition: `gates[slot] = (gates[slot] + byte) % bound`. Because adding the modulus (22 or 231) to a byte never changes that slot's gate value, some single-byte changes go undetected. For example, changing byte at position 0 (slot 0, bound 22) from 'A' (65) to 'W' (87) produces identical checksums since 65 % 22 = 87 % 22 = 21.

Measured detection rate: >99% of single-byte changes are detected (tested across all 256 byte values at every position of a 23-byte input). The undetected changes are those where the byte value shifts by exactly the modulus of its gate slot.

This is a known limitation of the 231-gate design. It is optimized for detecting common tampering (text edits, insertions, deletions, redactions), not for cryptographic proof of uniqueness. For the thesis track, this means sealed entries are tamper-*evident* for typical modifications, but not tamper-*proof* against a determined adversary who understands the gate derivation.

**Demo mode produces no numbers.** Without GCP credentials and an Intents API JWT, `fetch_data.py` returns empty arrays. No charts are generated and THESIS.md contains no figures — per the track prompt: "Never invent numbers."
