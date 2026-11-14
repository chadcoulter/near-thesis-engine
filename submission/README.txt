REAL-DATA DEMO — NEAR Thesis Engine

Entry 2 at redsigma.testnet on NEAR Testnet.
Store transaction: 2QawvYNZ3783ApE7vHUHNHS2mUT1g78uTu2CmuLaE3qA

BigQuery: 30 completed UTC days, October 15–November 13, 2026.
Intents: seven complete UTC days, November 7–13, 2026; 144,458 successful 1Click swaps.
Google project billing is disabled. Credentials are not included.

Run python scripts/verify_evidence.py --result submission/result.json to reconstruct all Intents totals offline.
Run python scripts/build_charts.py to reproduce the chart calculations from bundled data.
Install npm dependencies with npm ci; then run python scripts/dashboard_server.py and open http://127.0.0.1:8000.
Load submission/result.json, use entry ID 2, and click Retrieve + verify.
The saved result preserves the exact sealed payload, including original chart hashes.
Rebuilt PNG bytes can differ across operating systems; source data and numeric results remain inspectable.

The predictive comparison against token price is untested; no price baseline is fabricated.
