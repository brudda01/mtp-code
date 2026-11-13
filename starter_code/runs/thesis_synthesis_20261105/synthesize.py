"""R042: read-only synthesis of separately preserved studies; no simulator/API imports.

Run from any directory: python <this file>. Existing outputs are not overwritten.
"""
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import zipfile

OUT = Path(__file__).resolve().parent
BASE = OUT.parent.parent
REPO = BASE.parent
ARCHIVES = {
    'news_query_first_20261102_evidence.zip': '4ddbeca899dbe4e171468ce2de16692cdebd4e0cec4a734a24ed0dc7a3090176',
    'component_study_20261103_completed_evidence.zip': '89940c1eba9874b6686c9448197cf33979f9bb523fde6a8a47fd53de2b900ba9',
    'sequential_campaign_20261104_evidence.zip': '527bf047b71a0081b579a7530afe3311ec18ddf199dd7048f998e9ef1bd1e5de',
    'horizon_environment_20261104_evidence.zip': '28bd727d162f6a586b2c697634318d57822f1e5d52052adc92cd9f16202cb812',
    'news_execution_20261104_evidence.zip': '23fda86c514a776521b4d2359d4d2b1c61a9bb58ea943408f62491684dc47504',
    'news_source10729_20261104_evidence.zip': 'e3eda51c100d5eac2a7b59295e02509a691132e0df325a2019422a28d934b8c5',
    'initial_news_20261104_evidence.zip': '457fb1f642d759c5c7c5bfdd50d56e394cb6854b9f0395ff12c5378ca48ac669',
    'balanced_validation_20261104_evidence.zip': '04df396a0c84cf99ac66d5a842aae3168f2462caa2852dd7c78e52b7f326bb5b',
    'downside_confirmation_20261104_evidence.zip': 'b846393eedca7b694f4e99417cfa45cad43f89de78c69c50309d9a3c758db339',
}
NEWS = BASE/'runs/downside_confirmation_analysis_20261104'
NEWS_RAW = BASE/'runs/20261104_161605_downside_confirmation_1be3841b'
RULE = BASE/'runs/20261104_154730_market_validation_fff53e3b'
COMP = BASE/'runs/component_final_analysis_20261103'
SEQ = BASE/'runs/sequential_final_analysis_20261104'
sources = {}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    sources[path.relative_to(REPO).as_posix()] = sha(path)
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    sources[path.relative_to(REPO).as_posix()] = sha(path)
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9), (actual, expected)


def acf1(values):
    centered = [x-statistics.mean(values) for x in values]
    return sum(a*b for a, b in zip(centered, centered[1:]))/sum(x*x for x in centered)


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    assert not (OUT/'report.json').exists(), 'Preserve existing synthesis; do not overwrite.'
    start = read(OUT/'start_state.json')
    for path, digest in start['sha256'].items():
        assert sha(REPO/path) == digest, path
    for name, digest in ARCHIVES.items():
        path = BASE/'runs'/name
        assert sha(path) == digest, name
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None, name
    sealed = [
        (NEWS/'report.json', 'downside_confirmation_20261104_evidence.zip'),
        (NEWS/'mechanism_audit.json', 'downside_confirmation_20261104_evidence.zip'),
        (RULE/'report.json', 'balanced_validation_20261104_evidence.zip'),
        (RULE/'supplement/audit.json', 'balanced_validation_20261104_evidence.zip'),
        (COMP/'report.json', 'component_study_20261103_completed_evidence.zip'),
        (SEQ/'report.json', 'sequential_campaign_20261104_evidence.zip'),
    ]
    for path, archive_name in sealed:
        with zipfile.ZipFile(BASE/'runs'/archive_name) as archive:
            member = path.relative_to(REPO).as_posix()
            assert archive.read(member) == path.read_bytes(), member
    news = read(NEWS/'report.json')
    mechanism = read(NEWS/'mechanism_audit.json')
    rule = read(RULE/'report.json')
    audit = read(RULE/'supplement/audit.json')
    comp = read(COMP/'report.json')
    seq = read(SEQ/'report.json')

    # Recompute all news primary contrasts directly from executed raw trades.
    executions = {}
    for arm in news['arms']:
        assert arm['full_clean']
        trades = rows(NEWS_RAW/arm['run_path']/'trades.csv')
        key = (arm['seed'], arm['repetition'], arm['background'], arm['visible'])
        executions[key] = {actor: sum(int(t['quantity'])*((t['buyer_id']==actor)-(t['seller_id']==actor))
            for t in trades if int(t['round']) <= 3) for actor in ('llm_012','llm_013')}
    news_contrasts = []
    for contrast in news['headline_contrasts']:
        key = (contrast['seed'], contrast['repetition'], contrast['background'])
        values = {actor: executions[key+(True,)][actor]-executions[key+(False,)][actor]
                  for actor in ('llm_012','llm_013')}
        assert all(values[a] == contrast['actors'][a]['executed_net'] for a in values)
        assert sum(values.values()) == contrast['combined_executed']
        news_contrasts.append(dict(seed=key[0], repetition=key[1], background=key[2],
            Meera=values['llm_012'], Arjun=values['llm_013'], combined=sum(values.values()),
            mean_gap_difference=contrast['mean_gap_contrast']))
    background_differences = []
    for seed in sorted({x['seed'] for x in news_contrasts}):
        for rep in (1,2):
            pair = {x['background']: x for x in news_contrasts if x['seed']==seed and x['repetition']==rep}
            background_differences.append(pair['no_skew']['combined']-pair['original']['combined'])
    assert background_differences == [x['combined_response_difference'] for x in news['background_response_differences']]
    first_hashes = {x['messages_sha256'] for x in mechanism['first_visible_arjun']}
    assert len(first_hashes) == 1

    # Verify the post-hoc price-path-null example, including both wealth marks.
    pair = {x['visible']:x for x in news['arms'] if x['seed']==20611 and x['repetition']==2 and x['background']=='no_skew'}
    prices = {v:rows(NEWS_RAW/a['run_path']/'prices.csv') for v,a in pair.items()}
    for field in ('round','price','dividend','fundamental'):
        assert [r[field] for r in prices[True]] == [r[field] for r in prices[False]]
    assert [int(r['volume']) for r in prices[False]][4] - int(prices[True][4]['volume']) == 50
    accounts = {v:{x['agent_id']:x for x in a['full_horizon_evaluation']['accounts']} for v,a in pair.items()}
    transfer = {}
    for mark in ('auction','regime_benchmark'):
        transfer[mark] = {actor: accounts[True][actor]['marks'][mark]['active_minus_passive']
            -accounts[False][actor]['marks'][mark]['active_minus_passive'] for actor in ('llm_012','llm_013')}
        close(sum(transfer[mark].values()), 0)

    # Recompute the four paired rule contrasts from raw closing prices and MM states.
    rule_records = []
    for record in audit['records']:
        run = next(x for x in rule['runs'] if x['seed']==record['seed'] and x['cell']==record['cell'])
        price_rows = rows(RULE/run['run_path']/'prices.csv')
        states = rows(RULE/run['run_path']/'agents_state.csv')
        prices_ = [float(r['price']) for r in price_rows]
        previous = [100.0]+prices_[:-1]
        returns = [math.log(p/q) for p,q in zip(prices_,previous)]
        total = [math.log((p+float(r['dividend']))/q) for p,q,r in zip(prices_,previous,price_rows)]
        inventory = [int(s['shares']) for s in states if s['type']=='MarketMakerAgent']
        assert len(inventory)==len(price_rows)==600
        for value, expected in [(acf1(returns),record['price_acf1']), (acf1(total),record['total_acf1']),
            (acf1([abs(x) for x in total]),record['abs_total_acf1']),
            (sum(x in (0,300) for x in inventory)/600,record['boundary_fraction'])]: close(value, expected)
        rule_records.append({k:v for k,v in record.items() if k not in ('prices','maker_inventory')})
    means = {cell:{key:statistics.mean(x[key] for x in rule_records if x['cell']==cell)
        for key in audit['means'][cell]} for cell in ('original','no_skew')}
    for cell, metrics in means.items():
        for key,value in metrics.items(): close(value,audit['means'][cell][key])
    rule_pairs = []
    for pair_ in rule['paired_contrasts']:
        records = {x['cell']:x for x in rule_records if x['seed']==pair_['seed']}
        delta = records['no_skew']['price_acf1']-records['original']['price_acf1']
        close(delta,pair_['delta_acf1'])
        rule_pairs.append(dict(seed=pair_['seed'], price_acf1_difference=delta,
            boundary_difference=records['no_skew']['boundary_fraction']-records['original']['boundary_fraction'],
            block_price_acf1_differences=pair_['block_delta_acf1']))
    empirical = rule['empirical_context']
    empirical_returns = [x['log_total_return'] for x in empirical['records']]
    close(acf1(empirical_returns),empirical['acf_total'][0])
    close(acf1([abs(x) for x in empirical_returns]),empirical['acf_abs_total'][0])
    costs = comp['cost_by_condition_and_call_type']
    assert sum(x['reported_tokens'] for x in costs.values()) == comp['usage']['provider_reported_tokens']
    c6317 = next(x for x in seq['full_horizon_contrasts'] if x['seed']==6317 and x['contrast']=='C-B')
    result = dict(version='thesis_synthesis_v1_saved_evidence_only', date='2026-11-05', new_api_requests=0, new_markets=0,
        provenance=dict(revision=start['code_revision'], uncommitted_changes_record='start_state.json', sources='sources.json'),
        news=dict(study='R041', scenario_seeds=[20611,21727], model_repeats_per_cell=2, rounds=8,
            contrasts=news_contrasts, negative=sum(x['combined']<0 for x in news_contrasts),
            zero=sum(x['combined']==0 for x in news_contrasts), background_response_differences=background_differences,
            first_visible_Arjun_side_counts=mechanism['arjun_first_side_counts'], first_message_hashes=sorted(first_hashes),
            price_null_example=dict(seed=20611,repetition=2,background='no_skew',visible_minus_silent_passive_excess_currency=transfer),
            limitation='Eight nested contrasts, only two exogenous scenarios; not eight independent seeds. Unseeded provider draws. Downside at initial time only.'),
        background=dict(study='R039',paired_seeds=[x['seed'] for x in rule_pairs],rounds=600,
            records=rule_records,means=means,paired_contrasts=rule_pairs,
            empirical_context=dict(first_date=empirical['first_date'],last_date=empirical['last_date'],count=len(empirical_returns),
                total_return_acf1=acf1(empirical_returns),abs_total_return_acf1=acf1([abs(x) for x in empirical_returns]),source_sha256=empirical['sha256']),
            limitation='Four fresh rule-market scenario pairs; blocks nested, no long-run LLM validation. US portfolio reference is diagnostic, not a calibration/realism pass criterion.'),
        components=dict(studies=['R025-R027 fixed-state','R028-R030 sequential'],fixed_state_coverage=comp['coverage'],
            fixed_state_reported_costs=costs, fixed_state_unknown_usage_requests=comp['usage']['unknown_usage_requests'],
            sequential_complete_ABC_scenarios=seq['complete_ABC_scenarios'],partial_arms=seq['uncompleted_live_arms'],
            sequential_full_horizon_contrasts=seq['full_horizon_contrasts'],C6317_minus_B=c6317,
            limitation='Exploratory: four reused A-market frames, shared A-history reflections in conditional study; only one complete endogenous ABC scenario. Old ambiguous news wording/disclosed horizon; no pooling with R041 or causal wording comparison.'),
        audit=dict(source_archive_hashes_and_CRCs_verified=9,sealed_source_reports_and_audits_identical=len(sealed),
            raw_news_markets_checked=len(executions),raw_rule_markets_checked=len(rule_records),source_files_unchanged=len(start['sha256'])),
        next_decision='Synthesis first. A future fresh, quiet, matched endogenous ABC campaign would test stable component claims, if central to the thesis; not launched or predeclared here.')
    write(OUT/'report.json', result)
    write(OUT/'sources.json', dict(files=sources,archives=ARCHIVES,scope='Hashes refer to original preserved sources, not newly generated data.'))
    figure(rule_records)
    print(json.dumps(dict(audit=result['audit'],news_sign_counts=[result['news']['negative'],result['news']['zero']],
        price_null_transfer=transfer,background_means=means,component_costs=costs),indent=2))


def figure(records):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(1,2,figsize=(10.5,4.8))
    colors = ['#0072B2','#D55E00','#009E73','#CC79A7']
    for color,seed in zip(colors,sorted({x['seed'] for x in records})):
        pair = {x['cell']:x for x in records if x['seed']==seed}
        for ax,key,scale in [(axes[0],'price_acf1',1),(axes[1],'boundary_fraction',100)]:
            ax.plot([0,1],[pair[c][key]*scale for c in ('original','no_skew')],marker='o',color=color,label=str(seed))
    for ax in axes:
        ax.set_xticks([0,1],['Original skew 0.02','No skew'],fontsize=10)
        ax.grid(axis='y',alpha=.2)
        ax.spines[['top','right']].set_visible(False)
    axes[0].set_ylabel('Lag-1 log-price-return autocorrelation',fontsize=10)
    axes[1].set_ylabel('MM inventory at 0 or 300 (% sessions)',fontsize=10)
    axes[0].set_title('Less return dependence in all four pairs',fontsize=11)
    axes[1].set_title('More boundary time in all four pairs',fontsize=11)
    fig.suptitle('R039: market-background trade-offs across four fresh scenarios',fontsize=13)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',ncol=4,title='Four fresh matched scenario seeds',frameon=False,bbox_to_anchor=(.5,.015))
    fig.subplots_adjust(left=.085,right=.98,top=.80,bottom=.27,wspace=.55)
    for suffix in ('png','pdf'):
        fig.savefig(OUT/f'background_tradeoff.{suffix}',dpi=180,bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    main()
