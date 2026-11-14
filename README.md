# NEAR Thesis Engine — Verifiable Onchain Thesis

Built for the NEAR Hackathon 2026 **thesis** track. The research hypothesis is that cross-chain Intents volume is a better leading indicator of real NEAR usage than token price. The engine preserves the original thesis, counterarguments, chart calculations and 231-gate verification algorithm, and packages their evidence into a reproducible result that can be recorded and checked on NEAR Testnet.

The hypothesis remains **untested**: descriptive charts do not establish predictive power. Without data credentials, the engine reports missing evidence, generates no market figures, and still lets judges inspect and seal that explicitly incomplete research result.

## Architecture

```text
BigQuery + authenticated 1Click Explorer
              | scripts/fetch_data.py
              v
        data/raw_*.json
              | scripts/build_charts.py (existing calculations)
              v
 charts/*.png + manifest (queries, takeaways, input digest)
              | scripts/thesis_result.py + THESIS.md
              v
 canonical result JSON (raw evidence + thesis + manifest + PNG SHA-256)
              | scripts/seal_results.py -> scripts/near_client.mjs
              v
 Testnet redsigma.testnet: store_entry -> transaction hash + entry ID
              | get_entry + verify_entry
              v
 passing checksum AND exact retrieved-content equality
```

The Python dashboard server exposes this same workflow over a loopback-only API. The Node bridge uses a pinned `near-api-js` SDK and machine-readable transaction outcomes, rather than parsing human CLI output. Private keys stay in an existing credential file outside the repository; the browser never receives them.

## Install

Requirements: Python 3.14, Node.js >=22.22.2 (Node 24 recommended), and npm. Run from the repository root.

```sh
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
python -m playwright install chromium
```

Copy `.env.example` to `.env` (`cp .env.example .env`, or `Copy-Item .env.example .env` in PowerShell). The scripts load this file; existing process environment variables take precedence. `.env`, credentials, dependency directories, local evidence and generated artifacts are excluded from Git.

| Variable | Default / purpose |
|---|---|
| `NEAR_NETWORK` | `testnet`; other values are rejected |
| `NEAR_RPC_URL` | `https://rpc.testnet.near.org`; use a Testnet RPC |
| `SEALED_LOG_CONTRACT` | `redsigma.testnet` |
| `SEALED_LOG_AGENT` | `thesis-engine`; an informational string label, not an authenticated identity |
| `NEAR_SIGNER_ACCOUNT` | Funded `*.testnet` account used to sign writes |
| `NEAR_CREDENTIALS_FILE` | Absolute path to an existing NEAR CLI JSON credential outside this repository; its `account_id` must match the signer |
| `INTENTS_API_JWT` | Optional partner JWT for historical 1Click swaps |
| `INTENTS_WINDOW_DAYS` | `30`; complete UTC days, range 1–365 |
| `INTENTS_MAX_PAGES` | `20`; bounded pagination, range 1–1000 |
| `GOOGLE_APPLICATION_CREDENTIALS` | Optional GCP credential path; install `requirements-live.txt` to enable BigQuery |

Use a Testnet endpoint for `NEAR_RPC_URL`. The application rejects mainnet network configuration and non-Testnet contract/signer accounts. For signing, provision the credential through your wallet or NEAR CLI locally; never paste a private key into source, the dashboard, command-line arguments, or a pull request.

## Run the research and dashboard

```sh
python scripts/fetch_data.py
python scripts/build_charts.py
python scripts/seal_results.py --prepare
python scripts/dashboard_server.py
```

Open **http://127.0.0.1:8000**. Use the exact loopback URL printed by the server; `localhost` is intentionally not accepted by its host check. `--port 8001` selects another port. Opening the HTML as a local file is insufficient because submission and retrieval use the local API.

`--prepare` writes `artifacts/result.json` and `artifacts/store_args.json` without sending anything. The result is deterministic for identical evidence, chart assets and thesis text. Acquisition timestamps and query windows are part of the evidence, so fresh data pulls intentionally change the result. Chart paths are portable. An input digest prevents pairing a new raw-data pull with stale charts.

For live research, install `python -m pip install -r requirements-live.txt` and configure GCP and the partner JWT. BigQuery queries target the published `transactions` and `receipt_actions` tables, filter `block_date`, and preserve the SQL used in the result. GCP queries can incur charges.

The Intents adapter follows the [official Explorer API](https://docs.agentsonintents.com/integration/distribution-channels/1click-api/explorer/introduction) and [transaction schema](https://docs.agentsonintents.com/api-reference/get-transactions): `GET https://explorer.near-intents.org/api/v0/transactions`, `statuses=SUCCESS`, cursor pagination, and at least five seconds between pages. It sums `amountInUsd` by UTC creation date using decimal arithmetic before converting chart values to the existing numeric representation. Evidence includes the contributing transaction fields and requested window. A failed request, repeated transaction, malformed response or page-limit exhaustion produces an explicit source error and no partial volume chart. Narrow the window if needed. This source covers **1Click swaps**, not every NEAR Intents operation; days without returned observations are omitted.

The BigQuery column names follow the [NEAR Public Lakehouse export definitions](https://github.com/near/near-public-lakehouse/blob/main/src/lakehouse/notebooks/BQ%20Writer%20Stream.py). Source authorization and live data access have to be validated with your own configured accounts; offline fixtures are not empirical evidence.

## Judge demonstration

1. Click **Generate result**, or load the downloaded `artifacts/result.json`. Inspect the thesis, supporting evidence, errors, queries and available charts. Missing credentials are visibly labelled; no market numbers are invented.
2. Click **Download result** to retain the exact candidate bytes. The displayed result is the payload submitted in the next step.
3. With the contract deployed and a local Testnet signer configured, click **Submit to Sealed Log**. The application calls `store_entry`, waits for final execution, and displays the transaction hash, entry ID, contract and local SHA-256 identifier.
4. Expand the recorded entry to inspect `stored_by`, the timestamp, action data and checksums. `stored_by` is the authenticated transaction predecessor; `agent_id` is just a claim.
5. Click **Retrieve + verify**. Success requires `verify_entry` to return Boolean `true` and `get_entry.action_data` to equal the candidate string exactly.
6. Edit a character in the candidate and verify again. The dashboard displays **MISMATCH**. Even a known modular-checksum collision fails the exact comparison. An unused entry ID displays **NOT FOUND**, separately from false verification or an RPC error.
7. Click **Load ledger page** to read the public entry count and the next page cursor. This works without signing credentials once the contract exists.

The dashboard accepts a loaded result as supplied evidence; loading or sealing it does not authenticate its research provenance. Generated results commit the raw bundle, manifest, thesis and chart hashes. It never claims that a passing seal establishes the hypothesis or rules out cherry-picking.

## Testnet contract and deployment

Target: **`redsigma.testnet`**, exclusively on NEAR Testnet. The companion is [chadcoulter/near-sealed-log](https://github.com/chadcoulter/near-sealed-log). The integration was checked against [`contract/src/lib.rs` at commit `663315c`](https://github.com/chadcoulter/near-sealed-log/blob/663315cbdb2cb1fe87a14a8a8329686666a5139f/contract/src/lib.rs); the exact ABI and transaction requirements are documented in [CONTRACT_INTEGRATION.md](CONTRACT_INTEGRATION.md).

**Deployment check on November 14, 2026:** both the NEAR public Testnet RPC and FastNEAR Testnet RPC returned “contract code does not exist” for `redsigma.testnet`. The account exists, but its code hash was `11111111111111111111111111111111`. A signed store/retrieve/verify round trip cannot yet run there. No wallet credentials were found in this implementation environment. The companion's [contract build fix PR #2](https://github.com/chadcoulter/near-sealed-log/pull/2) was still open when inspected. This repository does not replace or modify that contract.

The companion was also **built locally from source** at commit `663315cbdb2cb1fe87a14a8a8329686666a5139f` using Rust/Cargo 1.100.0 and `cargo build --target wasm32-unknown-unknown --release`. The build succeeded. Node's WebAssembly validator accepted the artifact and confirmed exports for `new`, `store_entry`, `verify_entry`, `get_entry`, `get_entries_paginated`, `entry_count` and `get_owner`. Its SHA-256 is `58280a433ee5098e569ac5d526e7c9da3744e08873be8c5b4f0f86ae73ab0c76`. This validates compilation and module structure, not execution in NEAR's runtime. The separate companion CI/test fix remains under review.

The resolved dependency lockfile is retained at `deployment/companion.Cargo.lock`. To reproduce the source build (commands below use a POSIX shell; PowerShell equivalents are `Copy-Item` and the same Cargo commands):

```sh
git clone https://github.com/chadcoulter/near-sealed-log.git ../near-sealed-log
git -C ../near-sealed-log checkout 663315cbdb2cb1fe87a14a8a8329686666a5139f
cp deployment/companion.Cargo.lock ../near-sealed-log/contract/Cargo.lock
rustup toolchain install 1.100.0 --profile minimal
rustup target add wasm32-unknown-unknown --toolchain 1.100.0
cd ../near-sealed-log/contract
cargo +1.100.0 build --locked --target wasm32-unknown-unknown --release
# Produces target/wasm32-unknown-unknown/release/sealed_log.wasm
```

Use the built artifact or the companion's reviewed CI artifact. If the companion source changes, repeat source review, build and validation for that revision before deploying.

From the Thesis Engine repository root, this currently empty-code account can be deployed and initialized with [near-cli-rs](https://github.com/near/near-cli-rs/blob/main/docs/GUIDE.en.md):

```sh
near contract deploy redsigma.testnet use-file ../near-sealed-log/contract/target/wasm32-unknown-unknown/release/sealed_log.wasm with-init-call new json-args '{"owner":"redsigma.testnet"}' prepaid-gas '100 Tgas' attached-deposit '0 NEAR' network-config testnet sign-with-keychain send
```

This requires the account owner's wallet/keychain authorization for `redsigma.testnet`. Deployment and initialization are in one transaction. Recheck the account first: if another deployment has already initialized it, do not run `new` again or overwrite its state. A running dashboard needs no web build step; restart `python scripts/dashboard_server.py` after editing environment configuration. The local signing server is intended for a trusted local demo, not public hosting.

The alternative existing account `sealed-log-2026.testnet` was also checked on November 14, 2026: `get_owner` returned that account and `entry_count` returned 9, but `verify_entry`, `get_entry` and `get_entries_paginated` trapped with `WasmTrap(Unreachable)`. Pagination failed through both RPC providers. It is not a working fallback for this demonstration; the default remains `redsigma.testnet`.

After deployment:

```sh
python scripts/testnet_smoke.py
# Set NEAR_SIGNER_ACCOUNT and NEAR_CREDENTIALS_FILE in .env, then:
python scripts/seal_results.py
```

The first command checks all four view methods without a wallet. The second executes `store_entry` using the SDK with **100 Tgas, zero attached deposit, and FINAL execution**, records the transaction locally, retrieves the entry, and verifies both checksums and exact equality. Any failure exits nonzero. The signer pays gas; the nonpayable contract bears its storage growth. The signer can differ from the contract owner because `store_entry` is public.

There is no automatic resubmission after an ambiguous timeout. The transaction may already have landed: inspect Testnet history and retrieve the entry before trying again. If post-transaction verification fails, the local log retains the successful transaction hash and entry ID with the verification error.

## Independent verification

The exact submitted string is retained as `action_data` in `scripts/seal_log.json`, along with network, contract, SHA-256 and transaction metadata. Download it or retain `artifacts/result.json` before changing local inputs. The dashboard can verify any supplied candidate against an entry ID. From the CLI:

```sh
python scripts/seal_results.py --verify ENTRY_ID
```

This compares the entry with the **currently generated local result** and exits nonzero if missing or different. To compare an older saved result after changing local inputs, load its JSON in the dashboard and enter its original entry ID. The checksum script can be run entirely offline:

```sh
python scripts/verify.py
```

The original 231-gate scheme is a modular checksum, **not a collision-resistant cryptographic commitment**. For example, `A` and `W` collide in its first gate. Exact retrieved-content comparison protects this demo from accepting such collisions. SHA-256 identifies the local artifact; the stored full text remains necessary for independent comparison. See [THESIS.md](THESIS.md) for the research and gate limitations.

## Tests and reproducibility

```sh
python scripts/verify.py
python scripts/deep_edge_tests.py
python -m pytest -q
npm test
```

The tests include actual headless browser execution and a local HTTP server. Their in-memory ledger is explicitly a **test double**, not a deployed Testnet contract. SDK tests inspect actual invocation arguments and decode final transaction outcomes, failures and null views. Python tests cover chart generation, deterministic serialization, full Unicode evidence, stale evidence, retrieval, checksum collisions, byte limits, failure persistence, source adapters, and HTTP safety. Browser tests cover loading, generation, charts, downloading, submission, transaction display, retrieval, tamper checks, missing IDs, unsafe text and RPC failures.

Playwright uses its installed Chromium by default. To use an existing browser, set `TEST_BROWSER_EXECUTABLE` to its executable path. `.github/workflows/test.yml` installs dependencies, runs the same offline suites and prepares an unsigned demo artifact. Live RPC checks are explicit (`scripts/testnet_smoke.py`) so network outages or an undeployed external contract cannot masquerade as a passing integration test.

## Submission information

- Project: NEAR Thesis Engine; primary track: **thesis**.
- Repository: [chadcoulter/near-thesis-engine](https://github.com/chadcoulter/near-thesis-engine).
- Contract repository: [chadcoulter/near-sealed-log](https://github.com/chadcoulter/near-sealed-log).
- Intended contract: `redsigma.testnet`, NEAR Testnet.
- Research: [THESIS.md](THESIS.md), including evidence against the hypothesis and what would change it.
- Demo: `python scripts/dashboard_server.py`, then the seven-step workflow above.
- Reproducible result: `python scripts/seal_results.py --prepare`; attach the result JSON and transaction/entry evidence after a successful Testnet round trip.
- Outstanding submission dependencies: deploy the working companion WASM, authorize a Testnet signer, and supply real research credentials/data before presenting an empirically supported thesis. No submission upload or main-branch merge is performed by these scripts.
