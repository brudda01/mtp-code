"""Seal R042 derived artifacts; retain references to unchanged raw evidence ZIPs."""
import hashlib
import json
from pathlib import Path
import zipfile
from sim.llm.client import dotenv_api_key


def main():
    out = Path(__file__).resolve().parent
    repo = out.parents[2]
    runs = out.parent
    dest = runs/'thesis_synthesis_20261105_evidence.zip'
    assert not dest.exists()
    sources = json.loads((out/'sources.json').read_text())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    for name,digest in sources['archives'].items():
        assert sha(runs/name)==digest
    docs = ['THESIS_RESULTS.md','RESEARCH_DIARY.md','WORK_PLAN.tmp.md','AGENTS.md',
            '00_START_HERE.md','starter_code/README.md']
    artifact = {p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file() and p.name!='artifact_manifest.json'}
    artifact['../../../THESIS_RESULTS.md'] = sha(repo/'THESIS_RESULTS.md')
    with (out/'artifact_manifest.json').open('x',encoding='utf-8') as stream:
        json.dump(artifact,stream,indent=2)
        stream.write('\n')
    paths = [p for p in sorted(out.iterdir()) if p.is_file()]+[repo/name for name in docs]
    files = {p.relative_to(repo).as_posix():p.read_bytes() for p in paths}
    secrets = {value.encode() for name in ('API_KEY','BHARATCODE_API_KEY','GEMINI_API_KEY','NVIDIA_API_KEY')
               if (value:=dotenv_api_key(name)) and len(value)>=8}
    for name,data in files.items():
        assert '.env' not in Path(name).name and '.git' not in Path(name).parts
        assert not any(value in data for value in secrets), 'Configured secret export guard failed'
    manifest = dict(date='2026-11-05',scope='Derived synthesis and documentation only; raw evidence remains in nine referenced unchanged archives.',
        files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
        prior_archives=sources['archives'], configured_secret_scan_files=len(files),
        note='Documentation snapshot precedes final checksum closure to avoid circular hash. No .env or configured secret exported.')
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
        archive.writestr('EVIDENCE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(dest) as archive:
        assert archive.testzip() is None
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest()==digest
    result=dict(path=dest.relative_to(repo).as_posix(),sha256=sha(dest),bytes=dest.stat().st_size,
        exported_files=len(files),configured_secret_scan_files=len(files),prior_archives_unchanged=9,all_member_hashes_verified=True)
    with (runs/'thesis_synthesis_20261105_evidence_manifest.json').open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2)
        stream.write('\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
