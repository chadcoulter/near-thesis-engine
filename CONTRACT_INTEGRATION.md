# Sealed Log integration contract

Inspected source: `chadcoulter/near-sealed-log`, main commit `663315cbdb2cb1fe87a14a8a8329686666a5139f`, `contract/src/lib.rs`. Target deployment: **redsigma.testnet** on **testnet**. Source inspection establishes the ABI; a successful live smoke test is separately required to establish deployed behavior.

| Method | JSON arguments | JSON return | Invocation |
|---|---|---|---|
| `store_entry` | `agent_id: string`, `action_data: string` | numeric `u64` entry ID, starting at 1 | Signed change call, 0 deposit (method is nonpayable); application supplies 100 Tgas and waits for FINAL |
| `verify_entry` | `entry_id: numeric u64`, `action_data: string` | `true`, `false`, or `null` if missing | Read-only view |
| `get_entry` | `entry_id: numeric u64` | Entry object or `null` | Read-only view |
| `get_entries_paginated` | `from: numeric u64`, `limit: numeric u64` | `{entries: Entry[], next_from: numeric u64 or null}` | Read-only view; inclusive `from`, contract caps limit at 100 |
| `entry_count` | `{}` | numeric `u64` | Read-only view |

These are ordinary Rust `u64` fields, not NEAR SDK `U64` string wrappers. The application's entry ID boundary is JavaScript's positive safe integer range. `timestamp` is a nanosecond `u64`; browser JSON numeric rendering may round this metadata beyond 2^53. Verification compares the complete action string, not the rounded timestamp.

Entry fields: `entry_id`, `agent_id`, `action_data`, `checksums: {sum, linear, prod}`, `timestamp`, `stored_by`. `stored_by` records `env::predecessor_account_id()`. Anyone can call `store_entry`; `agent_id` is not checked against the signer. There is no attached storage deposit: contract balance funds its storage and the signer pays transaction gas. Do not pass a deposit to this nonpayable method.

Pagination details matter: the source returns `id + 1` when it reaches the requested page size, including when that was the last actual entry. Follow the cursor until an empty page or null cursor. A source edge case with `limit=0` can return one entry, so the application restricts limits to 1–100. Default dashboard pages are 10 entries. The contract enumerates IDs and may return an empty page past the end.

The SDK bridge reads JSON requests on stdin, calls the exact allowlisted methods, and emits one JSON response. It decodes `status.SuccessValue` from Base64 JSON only after successful final transaction execution, retains `transaction_outcome.id`, and rejects transaction failure, incomplete status, receipt failures, missing hash and nonnumeric or unsafe IDs. Failed calls propagate to CLI exit codes and dashboard errors. No private key is sent in process arguments or HTTP responses.

Sealing uses one complete canonical result JSON string containing the thesis, raw source data, manifest, queries, takeaways and chart SHA-256 identifiers. A local 512,000-byte UTF-8 limit rejects oversized results before sending. It never shortens evidence. This is an application limit, not a claimed contract payload guarantee; gas and available storage can impose a lower practical bound.

`verify_entry` checks only the preserved 231-gate checksums. The application separately retrieves the public entry and requires literal `action_data` equality. A checksum collision therefore cannot yield application-level “verified intact.” A null response is shown as missing, a false response as mismatch, and invalid responses/RPC failures as errors.

Transaction metadata is saved before post-write verification. A verification failure remains nonzero and leaves the hash, ID and error available for recovery. Ambiguous timeouts are not automatically retried as new writes. Read history or Testnet transaction history before resubmitting. Keep downloaded result JSON available: the checksum scheme does not prove provenance, lack of cherry-picking or correctness of the thesis.

Live check, November 14, 2026: the source-built contract was deployed and initialized at `redsigma.testnet` in transaction `CfqwJwujoueXKzu5vN5sHMDgAp53YYcWrTonp93WNNdn`. Final transaction status, owner `redsigma.testnet` and deployed code hash `6w8HmQ8uFQ3MewqU1Gnwk7JoKeAfmbeMBSQYdmzTukzZ` were independently queried and checked through Testnet RPC. All four view-method smoke checks passed.

The live result was stored as entry 1 in transaction `5t3aDBUGZehvARaxENTTvHhb4GLhKurdDZoNXmbafZLh`. Retrieval returned the exact submitted string; `verify_entry` returned true for the original, false for the same string with `!` appended, and null for missing ID 999999999. Pagination returned entry 1 with entry_count 1. The original result SHA-256 is `98d0b22be6e2e4f92faeb9ff904a94dd18d64a46ec46fac630fa08e0d8ef71ec`. These checks also ran through the actual dashboard HTTP API. Public metadata is retained in `deployment/testnet-demo.json`.

The first CLI invocation completed storage and verification, but its Unicode console export failed under Windows' legacy encoding. The durable log retained the successful transaction; no duplicate write was sent. CLI JSON output now uses escaped Unicode, with a regression test for a cp1252 console.

The suggested fallback `sealed-log-2026.testnet` has code and returns 9 from `entry_count`, but `verify_entry(1, ...)`, `get_entry(1)` and pagination from 1 trapped with `WasmTrap(Unreachable)`. Its owner view succeeds. No assumptions about the underlying state/schema cause are made, and it is not selected as a working alternative.

A local source build of the inspected companion revision succeeded with Rust 1.100.0. The WASM passed Node WebAssembly validation and exports the required ABI. SHA-256: `58280a433ee5098e569ac5d526e7c9da3744e08873be8c5b4f0f86ae73ab0c76`; lockfile: `deployment/companion.Cargo.lock`. The deployed runtime behavior was subsequently verified by the actual Testnet transactions and calls above.
