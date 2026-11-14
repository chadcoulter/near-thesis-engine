#!/usr/bin/env python3
"""Seal the complete, canonical thesis result, without truncating evidence."""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

from fetch_data import _load_env
from thesis_result import ROOT, canonical, generate

_load_env()
SEAL_LOG = ROOT / 'scripts' / 'seal_log.json'
MAX_PAYLOAD = 512_000  # Local safety limit; reject, never truncate.


def near(method, args):
    if os.environ.get('NEAR_NETWORK', 'testnet') != 'testnet':
        raise ValueError('Only testnet is supported')
    try:
        proc = subprocess.run(['node', str(ROOT / 'scripts' / 'near_client.mjs')],
                              input=canonical({'method': method, 'args': args}), capture_output=True,
                              text=True, encoding='utf-8', timeout=180, cwd=ROOT)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('NEAR timed out; transaction may have landed. Inspect testnet history before retrying.') from exc
    try:
        response = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError('NEAR bridge failed to return JSON. Run npm ci and use Node >=22.22.2.') from exc
    if proc.returncode or 'error' in response:
        raise RuntimeError(response.get('error', 'NEAR bridge failed'))
    return response['result']


def verify(entry_id, payload):
    entry = near('get_entry', {'entry_id': entry_id})
    response = near('verify_entry', {'entry_id': entry_id, 'action_data': payload})
    if response is not None and type(response) is not bool:
        raise RuntimeError('Invalid verification response')
    return {'entry': entry, 'contract_verification': response,
            'exact_match': entry is not None and entry.get('action_data') == payload,
            'verified_intact': response is True and entry is not None and entry.get('action_data') == payload}


def seal(label, payload):
    if len(payload.encode('utf-8')) > MAX_PAYLOAD:
        raise ValueError('Result exceeds 512000 UTF-8 bytes; reduce evidence scope explicitly. Nothing was submitted.')
    # Read history before sending: an unreadable log must not cause an unrecorded transaction.
    history = json.loads(SEAL_LOG.read_text(encoding='utf-8')) if SEAL_LOG.exists() else {'entries': []}
    tx = near('store_entry', {'agent_id': os.environ.get('SEALED_LOG_AGENT', 'thesis-engine'), 'action_data': payload})
    entry_id = tx.get('entry_id')
    if type(entry_id) is not int or entry_id < 1 or not tx.get('transaction_id'):
        raise RuntimeError('Invalid transaction result')
    record = {'label': label, **tx, 'network': 'testnet',
              'contract': os.environ.get('SEALED_LOG_CONTRACT', 'redsigma.testnet'),
              'action_data': payload, 'sha256': hashlib.sha256(payload.encode('utf-8')).hexdigest(),
              'sealed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'verified_intact': False}
    history['entries'].append(record)
    SEAL_LOG.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding='utf-8')
    try:
        record.update(verify(entry_id, payload))
        if not record['verified_intact']:
            raise RuntimeError('Stored result failed verification or exact content comparison')
    except Exception as exc:
        record['verification_error'] = str(exc)
        raise RuntimeError(f'Transaction {tx["transaction_id"]}, entry {entry_id} stored but verification failed: {exc}. Retrieve before resubmitting.') from exc
    finally:
        SEAL_LOG.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding='utf-8')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Write exact signing arguments without sending')
    parser.add_argument('--verify', type=int, metavar='ENTRY_ID')
    args = parser.parse_args()
    payload = canonical(generate())
    if args.prepare:
        folder = ROOT / 'artifacts'
        folder.mkdir(exist_ok=True)
        (folder / 'result.json').write_text(payload, encoding='utf-8')
        (folder / 'store_args.json').write_text(canonical({'agent_id': os.environ.get('SEALED_LOG_AGENT', 'thesis-engine'), 'action_data': payload}), encoding='utf-8')
        print('Prepared artifacts/result.json and artifacts/store_args.json; no transaction sent')
    elif args.verify is not None:
        result = verify(args.verify, payload)
        print(json.dumps(result, indent=2))
        if not result['verified_intact']:
            return 1
    else:
        # Escaped JSON preserves Unicode content on Windows consoles with legacy encodings.
        print(json.dumps(seal('thesis-result', payload), indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
