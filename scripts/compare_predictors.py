"""Fixed-protocol, expanding-window next-day usage forecasts; no future model fitting."""
import argparse
import base64
import csv
import datetime as dt
from decimal import Decimal
import hashlib
import html
import json
import os
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

MODELS=['persistence','seasonal_persistence','usage','usage_price','usage_intents','usage_price_intents']
PROTOCOL={'start_inclusive':'2026-08-16','end_exclusive':'2026-11-14','initial_train_pairs':45,
          'feature_start_index':7,'ridge_alpha':1.0,'target':'next-day log1p usage; errors measured on original counts',
          'usage_features':['log1p usage t','log1p usage t-1','log1p usage t-7','target weekday sine','target weekday cosine'],
          'price_features':['log price at t+1 midnight UTC','log one-day price return'],
          'intents_features':['log1p daily inbound USD volume','one-day log1p volume change'],
          'primary_metric':'MAE','targets':['daily_active_accounts','tx_count'],
          'uncertainty':'paired circular moving-block bootstrap of daily absolute-error differences',
          'bootstrap_block_days':7,'bootstrap_resamples':5000,'bootstrap_seed':20261115,
          'note':'Fixed before fitting this comparison, not externally preregistered. No tuning or model selection on holdout.'}


def ridge_predict(train_x,train_y,test_x,alpha=1.0):
    mean=train_x.mean(axis=0)
    scale=train_x.std(axis=0)
    scale=np.where(scale<1e-12,1,scale)
    x=(train_x-mean)/scale
    target_mean=train_y.mean()
    coefficients=np.linalg.solve(x.T@x+alpha*np.eye(x.shape[1]),x.T@(train_y-target_mean))
    return float(target_mean+((test_x-mean)/scale)@coefficients)


def bootstrap_ci(differences,block=7,resamples=5000,seed=20261115):
    rng=np.random.default_rng(seed)
    n=len(differences)
    starts=rng.integers(0,n,size=(resamples,int(np.ceil(n/block))))
    indexes=((starts[:,:,None]+np.arange(block))%n).reshape(resamples,-1)[:,:n]
    samples=np.asarray(differences)[indexes].mean(axis=1)
    return [float(x) for x in np.quantile(samples,[.025,.975])]


def align(network,price_response,intents):
    n={r['block_date']:r for r in network['rows']}
    s={r['date']:r for r in intents['data']['daily_swap_volume_usd']}
    p={}
    for millis,price in price_response['prices']:
        stamp=dt.datetime.fromtimestamp(millis/1000,dt.timezone.utc)
        if stamp.time()==dt.time(0):
            key=(stamp.date()-dt.timedelta(days=1)).isoformat()
            if key in p: raise ValueError('Duplicate daily price timestamp')
            if not np.isfinite(price) or price<=0: raise ValueError('Invalid price')
            p[key]=price
    dates=[(dt.date(2026,8,16)+dt.timedelta(days=i)).isoformat() for i in range(90)]
    missing={kind:[d for d in dates if d not in rows] for kind,rows in [('network',n),('intents',s),('price',p)]}
    if any(missing.values()): raise ValueError(f'Missing completed-day observations: {missing}')
    return [{'date':d,'daily_active_accounts':n[d]['daily_active_accounts'],'tx_count':n[d]['tx_count'],
             'intents_usd':s[d]['volume_usd_decimal'],'swap_count':s[d]['swap_count'],'near_usd_day_end_reference':p[d]} for d in dates]


def evaluate(rows,initial=45):
    volume=np.log1p([float(r['intents_usd']) for r in rows])
    price=np.log([r['near_usd_day_end_reference'] for r in rows])
    origins=np.arange(7,len(rows)-1)
    assert len(origins)-initial>=20
    predictions=[]
    results={}
    for target in PROTOCOL['targets']:
        raw=np.array([r[target] for r in rows],dtype=float)
        y=np.log1p(raw)
        xs={m:[] for m in MODELS[2:]}
        for t in origins:
            weekday=dt.date.fromisoformat(rows[t+1]['date']).weekday()
            usage=[y[t],y[t-1],y[t-7],np.sin(2*np.pi*weekday/7),np.cos(2*np.pi*weekday/7)]
            pf=[price[t],price[t]-price[t-1]]
            vf=[volume[t],volume[t]-volume[t-1]]
            for m,features in [('usage',usage),('usage_price',usage+pf),('usage_intents',usage+vf),('usage_price_intents',usage+pf+vf)]:
                xs[m].append(features)
        xs={m:np.array(x) for m,x in xs.items()}
        targets=np.array([y[t+1] for t in origins])
        errors={m:[] for m in MODELS}
        for position in range(initial,len(origins)):
            t=int(origins[position])
            for model in MODELS:
                if model=='persistence': pred=raw[t]
                elif model=='seasonal_persistence': pred=raw[t-6]
                else:
                    # Rows before position have target dates <= current origin day.
                    predicted_log=ridge_predict(xs[model][:position],targets[:position],xs[model][position],PROTOCOL['ridge_alpha'])
                    pred=max(0,float(np.expm1(predicted_log)))
                actual=raw[t+1]
                errors[model].append(actual-pred)
                predictions.append({'target':target,'model':model,'origin_date':rows[t]['date'],'target_date':rows[t+1]['date'],
                                    'last_training_target_date':rows[int(origins[position-1])+1]['date'],
                                    'training_pairs':position,'actual':float(actual),'prediction':float(pred)})
        metric={m:{'mae':float(np.mean(np.abs(e))),'rmse':float(np.sqrt(np.mean(np.square(e))))} for m,e in errors.items()}
        price_loss=np.abs(errors['usage_price'])
        intents_loss=np.abs(errors['usage_intents'])
        difference=price_loss-intents_loss
        comparisons={}
        for competitor in ['usage','usage_price']:
            delta=np.abs(errors[competitor])-intents_loss
            comparisons[competitor]={'mae_reduction_pct':100*(metric[competitor]['mae']-metric['usage_intents']['mae'])/metric[competitor]['mae'],
                                     'mean_absolute_error_advantage':float(delta.mean()),'block_bootstrap_95pct_interval':bootstrap_ci(delta)}
        results[target]={'forecast_days':len(price_loss),'metrics':metric,'intents_vs':comparisons,
                         'primary_direction':'intents_lower_MAE' if difference.mean()>0 else 'price_lower_MAE'}
    return predictions,results


def interpretation(results):
    lower=all(r['intents_vs']['usage_price']['mae_reduction_pct']>0 for r in results.values())
    robust=all(r['intents_vs']['usage_price']['block_bootstrap_95pct_interval'][0]>0 for r in results.values())
    adds=all(r['intents_vs']['usage']['mae_reduction_pct']>0 for r in results.values())
    persistence=all(r['metrics']['persistence']['mae']==min(m['mae'] for m in r['metrics'].values()) for r in results.values())
    sentences=[('The Intents-augmented model has lower MAE than the price-augmented model for both outcomes in this evaluation.' if lower else 'Intents does not have lower MAE than price for both outcomes in this evaluation.'),
               ('Both paired uncertainty intervals favor Intents over price.' if robust else 'The paired uncertainty intervals do not establish an Intents advantage over price for both outcomes.'),
               ('Intents also improves on usage-only MAE for both outcomes.' if adds else 'Intents does not improve on usage-only MAE for both outcomes.')]
    if persistence: sentences.append('Previous-day persistence has the lowest MAE among all six models for both outcomes.')
    sentences.append('This experiment supports the comparative hypothesis within this window.' if lower and robust and adds else 'This test does not establish that Intents is a reliably better leading indicator than price with incremental value over recent usage.')
    return ' '.join(sentences)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'artifacts/comparison-90d')
    args=parser.parse_args()
    out=args.output_dir
    out.mkdir(parents=True,exist_ok=True)
    (out/'protocol.json').write_text(json.dumps(PROTOCOL,indent=2),encoding='utf-8')
    paths=[ROOT/'data/comparison-90d/network.json',ROOT/'data/comparison-90d/price-response.json',ROOT/'data/intents-evidence/2026-08-16_2026-11-14/source.json']
    sources=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
    rows=align(*sources)
    predictions,results=evaluate(rows)
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    summary={'protocol':PROTOCOL,'source_hashes':hashes,'aligned_days':len(rows),'swap_records':sum(r['swap_count'] for r in rows),
             'total_intents_usd_decimal':str(sum((Decimal(r['intents_usd']) for r in rows),Decimal(0))),
             'first_forecast_date':predictions[0]['target_date'],'last_forecast_date':predictions[-1]['target_date'],
             'results':results,'sealed':False,'status':'Post-deadline research extension; original entry 2 is unchanged'}
    for filename,data in [('aligned-daily.csv',rows),('forecast-predictions.csv',predictions)]:
        with (out/filename).open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(data[0])); writer.writeheader(); writer.writerows(data)
    (out/'comparison-results.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    labels=['Previous\nday','Previous\nweek','Usage','Usage +\nprice','Usage +\nIntents','Usage +\nboth']
    for ax,(target,res) in zip(axes,results.items()):
        ax.bar(labels,[res['metrics'][m]['mae'] for m in MODELS],color=['#94a3b8']*3+['#4477aa','#228855','#8866aa'])
        ax.set_title('Active signer accounts' if target=='daily_active_accounts' else 'Transaction records')
        ax.set_ylabel('Next-day mean absolute error (lower is better)')
        ax.tick_params(axis='x',labelsize=8)
    fig.suptitle(f'Expanding-window forecasts: {summary["first_forecast_date"]} to {summary["last_forecast_date"]}')
    fig.savefig(out/'forecast-comparison.png',dpi=160); plt.close(fig)
    md=['# NEAR thesis: 90-day predictive comparison',
        'Post-deadline research extension. This analysis was produced after the hackathon deadline. It is not part of the entry-2 sealed payload. No new on-chain result has been submitted.',
        '## Finding\n\n'+interpretation(results),
        f'## Data\n\n90 completed UTC days: August 16–November 13, 2026. {summary["swap_records"]:,} successful 1Click records; ${Decimal(summary["total_intents_usd_decimal"]):,.2f} reported inbound value. BigQuery supplies daily transaction counts and distinct signing accounts. CoinGecko supplies NEAR/USD aggregate reference prices at 00:00 UTC; the t+1 midnight point is used as the end-of-day reference for day t. It is not an exchange OHLC close.',
        f'## Test design\n\nPredict next-day usage, separately for active signers and transactions. Use 45 initial training pairs and an expanding training window; {results["tx_count"]["forecast_days"]} future dates ({summary["first_forecast_date"]}–{summary["last_forecast_date"]}) are scored. Each forecast uses only features through its origin day and training targets observed by that day. Standardization is refit inside each training window. Ridge alpha is fixed at 1.0. There is no holdout tuning. All models are scored on exactly the same dates.',
        'The usage model includes log1p usage at t, t−1 and t−7 and target-weekday sine/cosine. The price model adds log reference price and its daily log return. The Intents model adds log1p inbound USD volume and its daily change. Both use two additional features. A combined model and previous-day/previous-week persistence baselines are included. Targets are fit in log1p units and evaluated as counts after inverse transformation; no inverse-transform bias correction is applied. Primary metric: mean absolute error (MAE). RMSE is secondary. This protocol was fixed before fitting this run, not externally preregistered.']
    html_parts=[]
    for target,res in results.items():
        title='Active signer accounts' if target=='daily_active_accounts' else 'Transaction records'
        md += [f'## {title}']
        table=['| Model | MAE ↓ | RMSE ↓ |','|---|---:|---:|']
        for model in MODELS:
            item=res['metrics'][model]
            table.append(f'| {model} | {item["mae"]:,.2f} | {item["rmse"]:,.2f} |')
        md.append('\n'.join(table))
        for base,c in res['intents_vs'].items():
            lo,hi=c['block_bootstrap_95pct_interval']
            md.append(f'\nCompared with {base}, adding Intents instead yields {c["mae_reduction_pct"]:+.2f}% MAE reduction. Mean paired error advantage: {c["mean_absolute_error_advantage"]:,.2f} counts; approximate 95% seven-day moving-block bootstrap interval [{lo:,.2f}, {hi:,.2f}]. Positive means Intents has lower error; an interval spanning zero does not distinguish the models reliably in this test.')
    md += ['## Interpretation and limits',
           'Judge the claim separately for both outcomes using the table above. Lower Intents MAE than price is evidence in favor within this window; higher MAE is evidence against. If Intents does not also beat the usage-only model, it has not shown incremental predictive usefulness over usage history. Mixed outcomes do not confirm a general leading-indicator claim. A confidence interval spanning zero leaves the comparison inconclusive.',
           'This is a small, single-period retrospective forecasting experiment. The downloaded historical series may have been revised; the test cannot reproduce what each API actually published in real time. It is a pseudo-out-of-sample evaluation, not a live forecasting trial. The protocol uses observed daily totals available after the UTC day ends, without modelling ingestion delays. Pearson correlation, causality, price returns and investment profitability are different questions. USD swap volume can co-move with asset prices; account counts are not unique humans. Multiple targets and model comparisons are reported without multiplicity-adjusted significance claims. Block-bootstrap intervals are approximate and sensitive to sample size and block choice.',
           '## Provenance and reproduction',
           'The Intents archive contains all contributing SUCCESS records in 33 compressed JSONL parts. Its 90-day pull resumes validated newer pages from the earlier collection, retaining their original bytes; older pages were collected later. Cursor pagination is not an atomic snapshot. The independently executed archive verifier reconstructs all daily decimal totals and checks archive hashes, record uniqueness, status and date bounds. Exact API/query provenance and source hashes accompany the result JSON.',
           'Run `python scripts/fetch_comparison_data.py` for network and price inputs; collect the documented 90-day window with `scripts/fetch_intents_history.py`; run `python scripts/compare_predictors.py`. The forecasting calculation is offline once its three input JSON files are available. The full per-swap audit archive is retained locally; aggregate inputs and forecast predictions are supplied for lightweight reproduction.',
           '![Forecast errors](forecast-comparison.png)']
    (out/'PREDICTIVE-COMPARISON.md').write_text('\n\n'.join(md),encoding='utf-8')
    for block in md:
        if block.startswith('!['): continue
        if block.startswith('#'):
            first,*rest=block.split('\n\n',1); level=len(first)-len(first.lstrip('#'))
            html_parts.append(f'<h{level}>{html.escape(first.lstrip("# "))}</h{level}>')
            if rest: html_parts.append('<p>'+html.escape(rest[0])+'</p>')
        elif block.startswith('|'):
            lines=block.splitlines()
            cells=lambda line: [c.strip() for c in line.strip('|').split('|')]
            head='<tr>'+''.join('<th>'+html.escape(c)+'</th>' for c in cells(lines[0]))+'</tr>'
            content=''.join('<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in cells(line))+'</tr>' for line in lines[2:])
            html_parts.append('<table><thead>'+head+'</thead><tbody>'+content+'</tbody></table>')
        else: html_parts.append('<p>'+html.escape(block)+'</p>')
    encoded=base64.b64encode((out/'forecast-comparison.png').read_bytes()).decode()
    html_parts.insert(5,f'<img alt="Out-of-sample forecast errors" src="data:image/png;base64,{encoded}">')
    style='body{font:17px/1.65 system-ui;color:#182a3a;max-width:1100px;margin:40px auto;padding:24px}h1,h2{color:#146351}img{max-width:100%}table{border-collapse:collapse;width:100%;font-size:15px}th,td{padding:10px;border:1px solid #ccd8df;text-align:left}th{background:#e9f4ee}p{overflow-wrap:anywhere}'
    (out/'NEAR-Predictive-Comparison.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NEAR Predictive Comparison</title><style>'+style+'</style>'+''.join(html_parts)+'</html>',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
