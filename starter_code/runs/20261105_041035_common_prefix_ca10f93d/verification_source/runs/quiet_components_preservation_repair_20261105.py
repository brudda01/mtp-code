"""Preserve already completed R043 data using absolute input paths.

The original completion failure, frozen sources and numerical analysis stay
unchanged. No model calls or experimental/analysis reruns occur here.
"""
from datetime import datetime, timezone
from pathlib import Path
import shutil
from sim.provenance import sha256, write_json
from runs import quiet_components_20261105 as d
from runs import quiet_components_finish_20261105 as completion


def normalize(path):
    resolved=Path(path).resolve()
    assert resolved.is_relative_to((d.BASE/'runs').resolve())
    return resolved


def main():
    root=normalize('runs/20261105_012335_quiet_components_5066abab')
    out=normalize('runs/quiet_components_analysis_20261105')
    d.validate(root)
    assert d.read(root/'summary.json')['status']=='completed'
    assert d.read(root/'postprocessing_failure.json')['error_type']=='ValueError'
    for name,digest in d.read(root/'postprocessing_plan.json')['source_sha256'].items():
        assert sha256(d.BASE/name)==digest,name
    for name,digest in d.read(out/'artifact_manifest.json').items():
        assert sha256(out/name)==digest,name
    # Regress the observed relative/absolute boundary before calling the OLD
    # preservation function. All normalized exported files must have repo paths.
    for path in (root/'baseline_execution.json',out/'report.json'):
        assert normalize(path.relative_to(d.BASE))==path
        path.relative_to(d.BASE.parent)
    shutil.copyfile(__file__,root/'preservation_repair_source.py')
    write_json(root/'preservation_repair_plan.json',dict(
        question='Can the original completed outputs be archived without rerunning any experiment or numerical analysis?',
        change='Normalize study/analysis directories to absolute paths before calling unchanged original preserve().',
        rationale='Original worker supplied relative paths to relative_to(absolute repo), raising ValueError before creating archive.',
        old_failure_sha256=sha256(root/'postprocessing_failure.json'),
        report_sha256=sha256(out/'report.json'),repair_source_sha256=sha256(__file__),
        checks='Relative/absolute inputs normalize identically; paths constrained within runs; original frozen code and every analysis artifact hash match.',
        new_api_requests=0,new_market_paths=0,new_analysis_runs=0))
    receipt=completion.preserve(root,out)
    write_json(root/'postprocessing_recovery.json',dict(
        status='analyzed_and_preserved',finished_utc=datetime.now(timezone.utc).isoformat(),
        original_failure_retained=True,repair='absolute path normalization only',
        analysis=out.relative_to(d.BASE).as_posix(),evidence=receipt,
        new_api_requests=0,new_market_paths=0,new_analysis_runs=0))
    print(receipt)


if __name__=='__main__':main()
