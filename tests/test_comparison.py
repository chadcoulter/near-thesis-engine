import copy
import datetime as dt
import numpy as np
import pytest
from compare_predictors import align, bootstrap_ci, evaluate, ridge_predict


def synthetic_rows():
    # Synthetic data are for isolation checks only, never the research result.
    return [{'date':(dt.date(2026,8,16)+dt.timedelta(days=i)).isoformat(),
             'daily_active_accounts':1000+3*i+(i%7)*19,'tx_count':10000+100*i+(i%7)*31,
             'intents_usd':str(10000+7*i*i),'swap_count':100+i,
             'near_usd_day_end_reference':2+i/1000} for i in range(90)]


def test_future_observations_cannot_change_earlier_forecasts():
    rows=synthetic_rows()
    original,_=evaluate(rows)
    modified=copy.deepcopy(rows)
    for row in modified[70:]:
        row['daily_active_accounts']*=3
        row['tx_count']*=4
        row['intents_usd']=str(float(row['intents_usd'])*5)
        row['near_usd_day_end_reference']*=2
    altered,_=evaluate(modified)
    cutoff=rows[70]['date']
    first=[p['prediction'] for p in original if p['origin_date']<cutoff]
    second=[p['prediction'] for p in altered if p['origin_date']<cutoff]
    np.testing.assert_array_equal(first,second)
    assert len(original)==37*6*2
    assert all(p['last_training_target_date']<=p['origin_date']<p['target_date'] for p in original)


def test_ridge_matches_independent_augmented_least_squares():
    rng=np.random.default_rng(17)
    x=rng.normal(size=(30,4)); y=rng.normal(size=30); test=rng.normal(size=4)
    standardized=(x-x.mean(0))/x.std(0)
    augmented=np.vstack([standardized,np.eye(4)])
    expected=y.mean()+((test-x.mean(0))/x.std(0))@np.linalg.lstsq(augmented,np.r_[y-y.mean(),np.zeros(4)],rcond=None)[0]
    assert ridge_predict(x,y,test)==pytest.approx(expected,abs=1e-12)


def test_midnight_price_alignment_and_missing_data_rejection():
    rows=synthetic_rows()
    network={'rows':[{'block_date':r['date'],'daily_active_accounts':r['daily_active_accounts'],'tx_count':r['tx_count']} for r in rows]}
    swaps={'data':{'daily_swap_volume_usd':[{'date':r['date'],'volume_usd_decimal':r['intents_usd'],'swap_count':r['swap_count']} for r in rows]}}
    prices={'prices':[[int((dt.datetime.fromisoformat(r['date']).replace(tzinfo=dt.timezone.utc)+dt.timedelta(days=1)).timestamp()*1000),r['near_usd_day_end_reference']] for r in rows]}
    assert align(network,prices,swaps)==rows
    prices['prices'].pop()
    with pytest.raises(ValueError,match='Missing completed-day'):
        align(network,prices,swaps)


def test_bootstrap_sign_and_reproducibility():
    assert bootstrap_ci(np.ones(37)*3)==[3,3]
    assert bootstrap_ci(np.ones(37)*-2)==[-2,-2]
    assert bootstrap_ci(np.arange(37))==bootstrap_ci(np.arange(37))
