"""Read-only evidence analysis: preserve missing seed outcomes as null, never zero."""
import argparse
import json
from pathlib import Path
import yaml
from research.goedel_cohort import BASE, read, write, digest, rows, validate, audit_financial
from research.analyze_final_extensions import check_live_inputs, verify_outputs

ROOT_NAMES = ('goedel_cohort_20261108', 'goedel_second_seed_20261108', 'goedel_second_seed_retry_20261108')


def analyze(dest):
    dest = Path(dest).resolve();dest.mkdir(parents=True, exist_ok=False)
    freeze = read(BASE.parent / 'DATA_COLLECTION_FROZEN.json')
    assert freeze['status'] == 'permanently_frozen'
    reports = [];old_cfg = None;old_personas = None;old_initial = None
    for index, name in enumerate(ROOT_NAMES):
        root = BASE / 'runs' / name;validate(root);verify_outputs(root)
        summary = read(root / 'summary.json');path = root / summary['run_path']
        cfg = yaml.safe_load((root / 'config.yaml').read_text())
        personas = read(path / 'personas.json');initial = rows(path / 'initial_state.csv')
        if index == 0:
            old_cfg, old_personas, old_initial = cfg, personas, initial
        else:
            assert personas == old_personas and initial == old_initial
            expected = dict(old_cfg, seed=31991, name='goedel_6LLM_B_cap10_s31991')
            if index == 2:
                expected = json.loads(json.dumps(expected))
                expected['llm_limits'].update(max_requests=179, max_reserved_tokens=2994480)
            assert cfg == expected
        calls = [json.loads(line) for line in (path / 'llm_calls.jsonl').read_text().splitlines()]
        transport = [json.loads(line) for line in (root / 'provider_transport.jsonl').read_text().splitlines()]
        assert len(calls) == summary['delivered_decisions']
        assert len(transport) == summary['usage']['requests_made']
        assert sum('response' in x for x in transport) == len(calls)
        checked = check_live_inputs(path);audit = audit_financial(path)
        assert checked['complete_actual_input_pairs_checked'] == len(calls)
        if index:
            assert summary['completed_rounds'] == 0
            for csv in ('prices.csv', 'orders.csv', 'trades.csv', 'agents_state.csv', 'cashflows.csv'):
                assert rows(path / csv) == [], csv
            assert not (root / 'evaluation.json').exists() and not (root / 'metrics.json').exists()
            assert initial == old_initial and audit['account_rounds'] == 0
        reports.append(dict(seed=cfg['seed'], root=root.relative_to(BASE).as_posix(),
            summary=summary, protocol_sha256=digest(root / 'protocol.json'),
            output_manifest_sha256=digest(root / 'output_manifest.json'),
            http_errors=[x['error'] for x in transport if 'error' in x],
            audit=audit, **checked,
            market_metrics=read(root / 'metrics.json') if summary['completed_rounds'] else None,
            financial_outcomes_available=bool(summary['completed_rounds']),
            no_round_audit_claim_when_zero_rounds=summary['completed_rounds'] == 0))
    partial = reports[1:]
    usage = {key: sum(r['summary']['usage'][key] for r in partial) for key in
        ('requests_made', 'reserved_tokens', 'provider_reported_tokens', 'unknown_usage_requests', 'failed_requests', 'blocked_requests')}
    assert usage['requests_made'] == 3 and usage['reserved_tokens'] == 16592
    assert usage['provider_reported_tokens'] == 803 and usage['unknown_usage_requests'] == 2
    assert all(r['http_errors'][0]['http_status'] == 429 for r in partial)
    result = dict(stage='R057 final collection closure', collection_status='permanently_frozen',
        planned_scenarios=2, attempted_scenarios=2, completed_scenarios=1,
        seed31991_delivered_decisions=1, seed31991_missing_decisions=149,
        seed31991_completed_rounds=0, seed31991_market_metrics=None,
        two_seed_mean=None, two_seed_contrast=None, seed31991_usage=usage,
        attempts=reports, configuration_and_persona_match='passed; only seed/name differ; amended attempt deducts prior failed request/reservation from safety ceilings',
        limitations='No second market path exists. Single unexecuted reply is retained but is not trading, a return, an inventory result or an independent market replication. HTTP429 is a provider availability outcome; precise quota cause is unknown. Zero audited account-rounds in missing seed are not positive conservation evidence. No pooled mean, stability comparison or two-seed result.',
        protocol_deviation='One disclosed re-entry after original first-request HTTP429 and zero behavioral replies. Original no-restart rule explicitly amended before any outcome; amended run then stopped after one reply and another429. No further restart.')
    write(dest / 'report.json', result)
    table = ('| Seed | Status | Cleared rounds | Delivered decisions | Mean reference gap |\n'
             '|---|---|---:|---:|---:|\n'
             '| 30841 | Completed | 25/25 | 150/150 | 16.06% |\n'
             '| 31991 | Stopped: HTTP 429 | 0/25 | 1/150 | Missing |\n')
    (dest / 'availability_table.md').write_text(table, encoding='utf-8')
    write(dest / 'output_manifest.json', {p.name: digest(p) for p in dest.iterdir() if p.is_file() and p.name != 'output_manifest.json'})
    print(json.dumps({k: v for k, v in result.items() if k != 'attempts'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--output', required=True)
    analyze(parser.parse_args().output)
