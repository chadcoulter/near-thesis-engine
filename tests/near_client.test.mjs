import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodeOutcome, execute } from '../scripts/near_client.mjs';

const outcome = (value=17) => ({transaction_outcome:{id:'transaction-hash'}, status:{SuccessValue:Buffer.from(JSON.stringify(value)).toString('base64')}, receipts_outcome:[]});
test('decodes final transaction hash and returned numeric ID', () => {
  assert.deepEqual(decodeOutcome(outcome()), {entry_id:17,transaction_id:'transaction-hash'});
});
test('rejects transaction failure, pending, malformed ID, and receipt failure', () => {
  for (const value of [{status:{Failure:{}}}, {status:'Started'}, outcome('17'), outcome(null), outcome(0),
    {...outcome(),receipts_outcome:[{outcome:{status:{Failure:{error:'failure'}}}}]}]) {
    assert.throws(() => decodeOutcome(value));
  }
});
test('all four view methods use exact contract arguments and finality without credentials', async () => {
  const cases = [['entry_count',{},42],['get_entry',{entry_id:1},null],['verify_entry',{entry_id:1,action_data:'x'},false],
    ['get_entries_paginated',{from:1,limit:10},{entries:[],next_from:null}]];
  for (const [method,args,result] of cases) {
    const provider = {callFunction: async actual => {
      assert.deepEqual(actual,{contractId:'redsigma.testnet',method,args,blockQuery:{finality:'final'}});
      return result;
    }};
    assert.deepEqual(await execute({method,args},{},{provider}),result);
  }
});
test('signed call uses separate signer, exact strings, zero deposit, 100 Tgas and FINAL', async () => {
  const args = {agent_id:'research-label',action_data:'complete payload \u{1F680}'};
  const env = {NEAR_SIGNER_ACCOUNT:'alice.testnet',NEAR_CREDENTIALS_FILE:'/external/credential.json'};
  let calls = 0;
  const account = {callFunctionRaw:async actual => {
    calls++;
    assert.deepEqual(actual,{contractId:'redsigma.testnet',methodName:'store_entry',args,gas:100000000000000n,deposit:0n,waitUntil:'FINAL'});
    return outcome();
  }};
  const result = await execute({method:'store_entry',args},env,{account,provider:{viewNodeStatus:async()=>({chain_id:'testnet'})},readFile:async () => JSON.stringify({account_id:'alice.testnet'})});
  assert.equal(calls,1); assert.equal(result.transaction_id,'transaction-hash');
});
test('blocks mainnet, missing credentials, wrong credential account and unknown methods', async () => {
  await assert.rejects(execute({method:'entry_count',args:{}},{NEAR_NETWORK:'mainnet'}),/Only testnet/);
  await assert.rejects(execute({method:'entry_count',args:{}},{SEALED_LOG_CONTRACT:'alice.near'}),/testnet account/);
  await assert.rejects(execute({method:'store_entry',args:{}},{}),/Signing required/);
  await assert.rejects(execute({method:'invented',args:{}},{}),/Unsupported/);
  await assert.rejects(execute({method:'store_entry',args:{}},{NEAR_SIGNER_ACCOUNT:'a.testnet',NEAR_CREDENTIALS_FILE:'x'},
    {provider:{viewNodeStatus:async()=>({chain_id:'testnet'})},readFile:async()=>'{"account_id":"b.testnet"}'}),/does not match/);
  await assert.rejects(execute({method:'store_entry',args:{}},{NEAR_SIGNER_ACCOUNT:'a.testnet',NEAR_CREDENTIALS_FILE:'x'},
    {provider:{viewNodeStatus:async()=>({chain_id:'mainnet'})},readFile:async()=>{throw Error('must not read key')}}),/refusing to sign/);
});
test('RPC and signing failures propagate without resubmission', async () => {
  await assert.rejects(execute({method:'entry_count',args:{}},{},{provider:{callFunction:async()=>{throw Error('RPC unavailable')}}}),/RPC unavailable/);
  let count = 0;
  await assert.rejects(execute({method:'store_entry',args:{}},{NEAR_SIGNER_ACCOUNT:'a.testnet',NEAR_CREDENTIALS_FILE:'x'},
    {provider:{viewNodeStatus:async()=>({chain_id:'testnet'})},readFile:async()=>'{"account_id":"a.testnet"}',account:{callFunctionRaw:async()=>{count++;throw Error('signing failure')}}}),/signing failure/);
  assert.equal(count,1);
});
