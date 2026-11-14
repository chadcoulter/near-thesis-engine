"""Deterministic evidence envelope; retains existing research and chart algorithms."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def generate(root=ROOT):
    files = sorted((root / 'data').glob('raw_*.json'))
    raw = json.loads(files[-1].read_text(encoding='utf-8')) if files else {'demo': True, 'sources': []}
    path = root / 'charts' / 'manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'charts': []}
    if path.exists() and manifest.get('input_sha256') != hashlib.sha256(canonical(raw).encode('utf-8')).hexdigest():
        raise ValueError('Chart manifest does not match latest raw data. Generate result or run scripts/build_charts.py.')
    demo = raw.get('demo', True) or manifest.get('demo', True)
    for source in raw.get('sources', []):
        for reference in source.get('evidence_files', []):
            evidence_path = (root / reference['path']).resolve()
            if not evidence_path.is_relative_to((root / 'data' / 'intents-evidence').resolve()):
                raise ValueError('Audit archive must be inside data/intents-evidence')
            if not evidence_path.is_file():
                raise ValueError(f'Audit archive is missing or differs: {reference["path"]}')
            with evidence_path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != reference['sha256']:
                    raise ValueError(f'Audit archive is missing or differs: {reference["path"]}')
    assets = {}
    for chart in manifest.get('charts', []):
        path = root / 'charts' / (chart['name'] + '.png')
        if not path.exists():
            raise ValueError(f'Missing chart asset: {path.name}')
        assets[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'schema': 'near-thesis-result/v1', 'demo': demo,
            'status': 'Hypothesis untested; missing live evidence' if demo else 'Descriptive evidence available; predictive hypothesis still requires testing',
            'thesis': (root / 'THESIS.md').read_text(encoding='utf-8'),
            'evidence': {'raw_data': raw, 'chart_manifest': manifest}, 'chart_sha256': assets}
