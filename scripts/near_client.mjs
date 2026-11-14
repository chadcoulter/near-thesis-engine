import { Account, JsonRpcProvider, teraToGas } from 'near-api-js';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

export function decodeOutcome(outcome) {
  const hash = outcome.transaction_outcome?.id ?? outcome.transaction?.hash;
  const status = outcome.status;
  if (!hash || !status || typeof status !== 'object' || !('SuccessValue' in status)) {
    throw new Error(`Transaction ${hash ?? '(unknown)'} failed or is incomplete: ${JSON.stringify(status)}`);
  }
  for (const receipt of outcome.receipts_outcome ?? []) {
    if (receipt.outcome?.status?.Failure) throw new Error(`Receipt failed for transaction ${hash}`);
  }
  const entryId = JSON.parse(Buffer.from(status.SuccessValue, 'base64').toString('utf8'));
  if (!Number.isSafeInteger(entryId) || entryId < 1) throw new Error(`Invalid entry ID for transaction ${hash}`);
  return { entry_id: entryId, transaction_id: hash };
}

export async function execute(request, env = process.env, deps = {}) {
  if ((env.NEAR_NETWORK ?? 'testnet') !== 'testnet') throw new Error('Only testnet is supported');
  const contract = env.SEALED_LOG_CONTRACT || 'redsigma.testnet';
  if (!contract.endsWith('.testnet')) throw new Error('Contract must be a testnet account');
  const provider = deps.provider ?? new JsonRpcProvider({ url: env.NEAR_RPC_URL || 'https://rpc.testnet.near.org' });
  if (['verify_entry', 'get_entry', 'get_entries_paginated', 'entry_count'].includes(request.method)) {
    return provider.callFunction({ contractId: contract, method: request.method, args: request.args, blockQuery: { finality: 'final' } });
  }
  if (request.method !== 'store_entry') throw new Error('Unsupported contract method');
  if (!env.NEAR_SIGNER_ACCOUNT?.endsWith('.testnet') || !env.NEAR_CREDENTIALS_FILE) {
    throw new Error('Signing required: set NEAR_SIGNER_ACCOUNT and NEAR_CREDENTIALS_FILE to an existing testnet credential outside the repository');
  }
  const status = await provider.viewNodeStatus();
  if (status.chain_id !== 'testnet') throw new Error('RPC is not Testnet; refusing to sign');
  const credential = JSON.parse(await (deps.readFile ?? readFile)(env.NEAR_CREDENTIALS_FILE, 'utf8'));
  if (credential.account_id !== env.NEAR_SIGNER_ACCOUNT) throw new Error('Credential account does not match signer');
  const account = deps.account ?? new Account(env.NEAR_SIGNER_ACCOUNT, provider, credential.private_key);
  const outcome = await account.callFunctionRaw({ contractId: contract, methodName: 'store_entry', args: request.args,
    gas: teraToGas('100'), deposit: 0n, waitUntil: 'FINAL' });
  return decodeOutcome(outcome);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    let input = '';
    for await (const chunk of process.stdin) input += chunk;
    console.log(JSON.stringify({ result: await execute(JSON.parse(input)) }));
  } catch (error) {
    const message = String(error.message).replace(/(?:ed25519|secp256k1):[A-Za-z0-9]+/g, '[redacted]');
    console.log(JSON.stringify({ error: message }));
    process.exitCode = 1;
  }
}
