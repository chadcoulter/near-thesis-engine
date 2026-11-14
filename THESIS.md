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

## Metrics computed from live data

This snapshot uses real NEAR mainnet research data, with its verification record on **NEAR Testnet**. BigQuery covers **2026-10-15 through 2026-11-13** (30 completed UTC days). Contract usage and Intents cover **November 7–13, 2026** (7 completed UTC days). The shorter Intents window was selected for the demo deadline only after cursor pagination had crossed its lower boundary; no partial day or incomplete page total is reported.

| Observation | Measured result |
|---|---:|
| Daily active signer accounts, first → last day | 55,503 → 85,595 |
| Change in daily active signers, first vs last day | 54.22% |
| Total transactions over 30 days | 20,344,165 |
| Daily transactions, first → last day | 911,980 → 1,036,324 |
| Most-called contract, trailing 7 days | `game.hot.tg` — 1,952,431 function-call actions |
| Successful 1Click swaps in the complete 7-day window | 144,458 |
| Reported inbound USD volume over those 7 days | $289,787,516.06 |
| Intents daily volume, first → last observed day | $29,084,781.89 → $59,747,874.26 |

The USD values are the Explorer API's `amountInUsd`, counted once per successful swap and summed by UTC creation date using decimal arithmetic. They describe **1Click** activity, not all NEAR Intents activity. Active signers are accounts, not verified humans. Transaction counts include the table's transaction records; contract counts measure receipt function-call actions.

All 144,458 contributing swap records are retained in 4 gzip JSONL audit parts. The result commits each compressed file and its uncompressed content with SHA-256. `python scripts/verify_evidence.py` independently reconstructs the daily totals offline. Query windows, actual SQL, BigQuery job IDs, processed bytes and archive hashes are included in the result evidence. Google project billing is disabled.

## Metrics that could NOT be computed

- Relative predictive performance against token price: this snapshot has no NEAR/USD price baseline.
- A credible 90+ day Granger or out-of-sample leading-indicator test: the Intents demo window is only seven days.
- Organic versus incentivized volume, unique human users, and activity outside the 1Click Explorer's coverage.

These metrics are not invented or inferred from the descriptive charts.

## Evidence FOR the claim

The data establish observable settlement activity and network usage: 144,458 successful 1Click swaps represent $289,787,516.06 of reported inbound volume, while the 30-day network window contains 20,344,165 transactions. Daily active signer counts rose 55,503 → 85,595. This supports measuring economic activity directly rather than relying only on token price.

It does **not** establish that Intents volume leads network activity, or that it outperforms price. The windows differ, endpoint comparisons are not predictive models, and a seven-day sample cannot support that conclusion.

## Evidence AGAINST the claim

- **Correlation vs causation**: Intents volume could rise because of a single large airdrop or incentive program, not organic usage. We don't distinguish organic vs incentivized volume.
- **Sample size and window alignment**: BigQuery has 30 daily observations, but Intents has seven completed days in this deadline-limited snapshot. Any comparison must use overlapping dates. A predictive claim still needs a substantially longer series and an actual price baseline.
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

On November 14, 2026, the companion contract was built from source and deployed to `redsigma.testnet`, with owner `redsigma.testnet`, in Testnet transaction `CfqwJwujoueXKzu5vN5sHMDgAp53YYcWrTonp93WNNdn`. Deployment and initialization succeeded. Each thesis result must still be retrieved and compared individually; deployment alone does not verify a result or establish the research hypothesis. See README.md for the recorded live demonstration and CONTRACT_INTEGRATION.md for the inspected ABI.

## Dashboard

Run `python scripts/dashboard_server.py` and open `http://127.0.0.1:8000`. Generate or load a result; inspect its supporting evidence; submit it with a locally configured Testnet signer; inspect the transaction identifier; retrieve the entry; and verify the exact content. Missing data, missing entries, mismatches and RPC failures are displayed separately.

The chart calculations remain descriptive. The Explorer adapter aggregates complete bounded windows of successful **1Click** swaps, not all Intents activity. It omits days without returned transactions and refuses partial totals when pagination fails or reaches its limit. Source errors remain visible in the result. The live credentialed data paths require GCP and partner API authorization; offline test fixtures are not research evidence.

## Known Limitations

**231-gate tamper detection is not cryptographic collision resistance.** The gate derivation uses modular addition: `gates[slot] = (gates[slot] + byte) % bound`. Because adding the modulus (22 or 231) to a byte never changes that slot's gate value, some single-byte changes go undetected. For example, changing byte at position 0 (slot 0, bound 22) from 'A' (65) to 'W' (87) produces identical checksums since 65 % 22 = 87 % 22 = 21.

Measured detection rate: >99% of single-byte changes are detected (tested across all 256 byte values at every position of a 23-byte input). The undetected changes are those where the byte value shifts by exactly the modulus of its gate slot.

This is a known limitation of the 231-gate design. It is optimized for detecting common tampering (text edits, insertions, deletions, redactions), not for cryptographic proof of uniqueness. For the thesis track, this means sealed entries are tamper-*evident* for typical modifications, but not tamper-*proof* against a determined adversary who understands the gate derivation.

**Demo mode produces no numbers.** Without GCP credentials and an Intents API JWT, `fetch_data.py` returns empty arrays. No charts are generated and THESIS.md contains no figures — per the track prompt: "Never invent numbers."
