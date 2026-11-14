"""Build a descriptive report from the frozen entry-2 snapshot without changing it."""
import argparse
import base64
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'artifacts' / 'research-report')
    args = parser.parse_args()
    snapshot = ROOT / 'submission' / 'result.json'
    before = snapshot.read_bytes()
    raw_path = ROOT / 'data' / 'raw_20261114_222544.json'
    raw = json.loads(raw_path.read_text(encoding='utf-8'))
    sources = {s['source']: s for s in raw['sources']}
    chain = sources['near-bigquery']['data']
    swaps = sources['near-intents-explorer']['data']['daily_swap_volume_usd']
    accounts = {r['block_date']: r['daily_active_accounts'] for r in chain['daily_active_accounts']}
    txs = {r['block_date']: r['tx_count'] for r in chain['transaction_counts']}
    dates = sorted(accounts)
    days = [r['date'] for r in swaps]
    assert len(dates) == 30 and len(days) == 7 and len(set(days)) == 7
    assert all(d in accounts and d in txs for d in days)
    volume = sum((Decimal(r['volume_usd_decimal']) for r in swaps), Decimal(0))
    count = sum(r['swap_count'] for r in swaps)
    volume_values = [float(Decimal(r['volume_usd_decimal'])) for r in swaps]
    account_values = [accounts[d] for d in days]
    tx_values = [txs[d] for d in days]
    corr_accounts = statistics.correlation(volume_values, account_values)
    corr_txs = statistics.correlation(volume_values, tx_values)
    lag_accounts = statistics.correlation(volume_values[:-1], account_values[1:])
    lag_txs = statistics.correlation(volume_values[:-1], tx_values[1:])
    change = lambda last, first: (Decimal(last) / Decimal(first) - 1) * 100
    first_week = dates[:7]
    last_week = dates[-7:]
    account_week_change = change(sum(accounts[d] for d in last_week), sum(accounts[d] for d in first_week))
    tx_week_change = change(sum(txs[d] for d in last_week), sum(txs[d] for d in first_week))
    record = json.loads((ROOT / 'submission/seal-record.json').read_text())
    assert hashlib.sha256(before).hexdigest() == record['sha256'], 'Sealed payload changed'
    stats = {'raw_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest(),
             'sealed_payload_sha256': record['sha256'], 'swap_count': count,
             'volume_usd_decimal': str(volume), 'mean_swap_usd': str(volume / count),
             'accounts_first_vs_last_week_pct': float(account_week_change),
             'transactions_first_vs_last_week_pct': float(tx_week_change),
             'same_day_pearson': {'n': 7, 'active_signers': corr_accounts, 'transactions': corr_txs},
             'volume_today_usage_next_day_pearson': {'n': 6, 'active_signers': lag_accounts, 'transactions': lag_txs}}
    md, body = [], []
    def heading(text, level=2):
        md.append('#' * level + ' ' + text)
        body.append(f'<h{level}>{html.escape(text)}</h{level}>')
    def paragraph(text):
        md.append(text)
        body.append('<p>' + html.escape(text) + '</p>')
    def table(headers, rows):
        md.append('| ' + ' | '.join(headers) + ' |\n|' + '|'.join(['---'] * len(headers)) + '|\n' + '\n'.join('| ' + ' | '.join(map(str, row)) + ' |' for row in rows))
        body.append('<div class="table"><table><thead><tr>' + ''.join('<th>'+html.escape(str(x))+'</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows) + '</tbody></table></div>')
    heading('NEAR Thesis Engine: economic activity with verifiable evidence', 1)
    paragraph('Investment Thesis track · NEAR HACKATHON 2026 · Research snapshot: November 14, 2026. This expanded analysis was written after entry 2 was sealed. Entry 2 commits the original result and its evidence, not the text or new calculations in this report.')
    heading('Investment thesis and current finding')
    paragraph('The research hypothesis is that NEAR Intents settlement activity can predict subsequent NEAR network usage better than NEAR token price. The investment rationale is to examine observable economic activity alongside market valuation. This dataset establishes measurable 1Click activity and a reproducible evidence workflow. It does not yet establish predictive superiority, causality, token value accrual or an investment return.')
    paragraph(f'The frozen snapshot contains {count:,} successful 1Click swaps and ${volume:,.2f} of reported inbound USD value over November 7–13. The network series contains {sum(txs.values()):,} transaction records over October 15–November 13. These windows end before November 14 UTC and exclude the incomplete current day.')
    heading('Measured network activity')
    table(['Measure', 'Result', 'Interpretation'], [
        ['Daily active signers, first → last day', f'{accounts[dates[0]]:,} → {accounts[dates[-1]]:,} ({change(accounts[dates[-1]],accounts[dates[0]]):+.2f}%)', 'Accounts signing transactions; not unique humans'],
        ['Daily transactions, first → last day', f'{txs[dates[0]]:,} → {txs[dates[-1]]:,} ({change(txs[dates[-1]],txs[dates[0]]):+.2f}%)', 'Transaction records; not receipt actions'],
        ['Mean daily active signers, first / last seven days', f'{statistics.mean(accounts[d] for d in first_week):,.0f} / {statistics.mean(accounts[d] for d in last_week):,.0f} ({account_week_change:+.2f}%)', 'Oct 15–21 versus Nov 7–13; averages reduce endpoint dependence'],
        ['Mean daily transactions, first / last seven days', f'{statistics.mean(txs[d] for d in first_week):,.0f} / {statistics.mean(txs[d] for d in last_week):,.0f} ({tx_week_change:+.2f}%)', 'Same nonoverlapping seven-day windows'],
        ['Most-called observed contract, Nov 7–13', 'game.hot.tg — 1,952,431 function-call actions', 'Activity rank is not a measure of revenue or unique users']])
    heading('Seven-day aligned evidence')
    table(['UTC date', '1Click swaps', 'Inbound USD', 'Mean USD / swap', 'Active signers', 'Transactions'],
          [[r['date'], f"{r['swap_count']:,}", f"${Decimal(r['volume_usd_decimal']):,.2f}", f"${Decimal(r['volume_usd_decimal']) / r['swap_count']:,.2f}", f"{accounts[r['date']]:,}", f"{txs[r['date']]:,}"] for r in swaps])
    paragraph(f'The mean reported inbound value is ${volume / count:,.2f} per swap. Daily volume changes {change(swaps[-1]["volume_usd_decimal"],swaps[0]["volume_usd_decimal"]):+.2f}% from the first to last day; swap count changes {change(swaps[-1]["swap_count"],swaps[0]["swap_count"]):+.2f}%. Volume therefore reflects both transaction frequency and average transaction size. This is a descriptive endpoint comparison, not a trend estimate or evidence of future performance.')
    paragraph('USD totals sum the Explorer amountInUsd once per SUCCESS record by its UTC creation date, using decimal arithmetic. They cover the 1Click Explorer population, not all NEAR Intents activity, fees, protocol revenue, NEAR-denominated demand or unique people. The source records are observations from a mutable service; later settlements or backfills can change a future pull.')
    heading('Exploratory relationship with network usage')
    table(['Comparison', 'Paired days', 'Pearson r'], [
        ['Same-day 1Click volume and active signers', 7, f'{corr_accounts:.3f}'],
        ['Same-day 1Click volume and transactions', 7, f'{corr_txs:.3f}'],
        ['Today’s volume and next day’s active signers', 6, f'{lag_accounts:.3f}'],
        ['Today’s volume and next day’s transactions', 6, f'{lag_txs:.3f}']])
    paragraph('These correlations use the overlapping dates only, raw daily levels, no detrending and no controls. The lagged calculation pairs November 7–12 volume with November 8–13 usage. Six or seven observations cannot distinguish stable predictive content from coincident trends, weekday effects or an outlier. No significance or causal claim is made, and these calculations do not compare against price. They are diagnostics for designing the next study, not confirmation of the hypothesis.')
    heading('Charts from the sealed evidence')
    for name, title in [('daily_active_accounts', 'Daily active signer accounts'), ('transaction_counts', 'Daily transaction records'), ('contract_usage', 'Observed contract function-call activity'), ('intents_swap_volume', 'Successful 1Click inbound USD volume')]:
        md.append(f'### {title}\n\n![{title}](charts/{name}.png)')
        encoded = base64.b64encode((ROOT / f'charts/{name}.png').read_bytes()).decode()
        body.append(f'<figure><img alt="{html.escape(title)}" src="data:image/png;base64,{encoded}"><figcaption>{html.escape(title)}</figcaption></figure>')
    heading('Counterarguments and investment implications')
    paragraph('Higher swap activity could reflect incentives, routing changes, repeated automated transactions or larger tickets rather than durable adoption. Activity concentrated in a popular application may reverse. Even persistent cross-chain activity does not establish that fees, token holding demand or investor returns rise proportionally. USD volume can also change with underlying asset prices. The report therefore supports monitoring economic use, while leaving the valuation and forecasting bridges to be measured.')
    heading('What would strengthen or weaken the thesis')
    paragraph('Collect at least 90 aligned daily observations as an initial study, and preferably multiple market regimes. Freeze the sample boundary and obtain a documented NEAR/USD price series. Compare rolling forecasts for next-day active signers and transaction counts: a usage-history baseline; usage plus price features; usage plus Intents features; and the combined model. Choose lags and transformations using training data only, reserve future observations for evaluation, and compare forecast error with uncertainty and sensitivity to unusual days. Ninety days is a starting sample, not a guarantee of sufficient power.')
    paragraph('Consistent out-of-sample improvement from Intents features over both the usage-only and price-feature baselines would strengthen the claim. No improvement, reversal across periods, or dependence on a handful of unusually large swaps would weaken it. A rise in volume while price is flat, or a single Granger-test p-value, would not by itself prove the comparative leading-indicator claim.')
    heading('Provenance and verification')
    paragraph('BigQuery tables: bigquery-public-data.crypto_near_mainnet_us.transactions and bigquery-public-data.crypto_near_mainnet_us.receipt_actions. Queries use explicit lower-inclusive, upper-exclusive block_date parameters. Intents endpoint: https://explorer.near-intents.org/api/v0/transactions. The complete seven-day subwindow was retained after contiguous newest-first pagination crossed its lower boundary; the attempted longer pull was stopped for the demo deadline. Four gzip JSONL parts preserve all contributing records, with compressed and uncompressed SHA-256 hashes.')
    table(['Verification item', 'Value'], [['Network / contract', 'NEAR Testnet / redsigma.testnet'], ['Entry', 2], ['Store transaction', record['transaction_id']], ['Sealed payload SHA-256', record['sha256']], ['Frozen raw-data SHA-256', stats['raw_sha256']], ['Original candidate check', 'Contract verification true AND exact retrieved-content equality true'], ['One-character edit demonstration', 'Contract verification false AND exact equality false']])
    paragraph('Sealed Log preserves the existing 231-gate checksums, which have known collisions and are not cryptographic collision resistance. The app also compares the retrieved action_data string exactly. A matching record establishes the demonstrated content comparison; it does not authenticate the upstream data provider, prove completeness of the external API, or validate the research hypothesis. SHA-256 identifies the local evidence artifacts.')
    heading('Reproduce the report')
    paragraph('From the feature branch, install the documented dependencies, then run: python scripts/verify_evidence.py --result submission/result.json ; python scripts/build_research_report.py . The first command streams and checks every archived swap and reconstructs daily totals; the second produces this report and machine-readable analysis offline. Commands are separate steps. Credentials and a fresh API pull are not needed for the frozen evidence. Live data refreshes require your own GCP and Explorer authorization.')
    paragraph('Source: https://github.com/chadcoulter/near-thesis-engine/tree/feat/testnet-hackathon-demo . Public transaction: https://testnet.nearblocks.io/txns/' + record['transaction_id'])
    report_md = '\n\n'.join(md) + '\n'
    (ROOT / 'REPORT.md').write_text(report_md, encoding='utf-8')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'research-analysis.json').write_text(json.dumps(stats, indent=2) + '\n', encoding='utf-8')
    style = 'body{font:17px/1.65 system-ui,sans-serif;color:#152238;background:#f4f6fa;margin:0}main{max-width:1100px;margin:auto;background:white;padding:48px}h1{font-size:36px;line-height:1.2}h2{margin-top:38px;color:#164d48}p{overflow-wrap:anywhere}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;border:1px solid #cbd5e1;text-align:left}th{background:#e9f5f1}figure{margin:30px 0}img{max-width:100%;height:auto}figcaption{color:#536378} @media print{body,main{background:white}main{padding:0}h2{break-after:avoid}figure,tr{break-inside:avoid}}'
    (args.output_dir / 'NEAR-Investment-Thesis-Report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEAR Investment Thesis — Research Report</title><style>'+style+'</style><main>'+'\n'.join(body)+'</main></html>', encoding='utf-8')
    assert snapshot.read_bytes() == before
    print(json.dumps(stats, indent=2))


if __name__ == '__main__':
    main()
