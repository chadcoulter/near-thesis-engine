#!/usr/bin/env python3
"""Read-only deployed-contract check. Requires no wallet and never submits a transaction."""
import json
import sys
from seal_results import near


def main():
    count = near('entry_count', {})
    if type(count) is not int or count < 0:
        raise RuntimeError('entry_count returned an invalid value')
    page = near('get_entries_paginated', {'from': 1, 'limit': 10})
    if not isinstance(page, dict) or not isinstance(page.get('entries'), list) or 'next_from' not in page:
        raise RuntimeError('Invalid pagination response')
    missing = count + 1
    if near('get_entry', {'entry_id': missing}) is not None:
        raise RuntimeError('Missing entry should return null (or ledger changed; rerun)')
    if near('verify_entry', {'entry_id': missing, 'action_data': 'nonexistent'}) is not None:
        raise RuntimeError('Missing verification should return null (or ledger changed; rerun)')
    if page['entries']:
        entry = page['entries'][0]
        retrieved = near('get_entry', {'entry_id': entry['entry_id']})
        if retrieved != entry or near('verify_entry', {'entry_id': entry['entry_id'], 'action_data': entry['action_data']}) is not True:
            raise RuntimeError('Existing entry retrieval or verification failed')
    print(json.dumps({'network':'testnet', 'entry_count':count, 'view_methods':'all four passed',
                      'write_test':'not performed; run scripts/seal_results.py with a configured signer'}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'TESTNET CHECK BLOCKED: {exc}', file=sys.stderr)
        sys.exit(1)
