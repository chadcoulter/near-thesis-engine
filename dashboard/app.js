const $ = id => document.getElementById(id);
let payload = '', busy = false;
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function show(id, value) { $(id).textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
async function run(action) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => button.disabled = true);
  show('error', '');
  try { await action(); } catch (error) { show('error', error.message); }
  finally { busy = false; document.querySelectorAll('button').forEach(button => button.disabled = false); }
}
function loadResult(data) {
  const result = JSON.parse(data.action_data);
  if (result.schema !== 'near-thesis-result/v1') throw new Error('Unsupported result schema');
  payload = data.action_data;
  show('researchStatus', result.status);
  show('mode', result.demo ? 'DEMO / MISSING EVIDENCE — no market figures invented' : 'Research evidence loaded — hypothesis requires predictive testing');
  show('thesis', result.thesis);
  show('evidence', result.evidence);
  $('candidate').value = payload;
  show('verification', 'Result loaded. Submit or enter an existing entry ID to verify.');
  $('charts').replaceChildren();
  for (const chart of result.evidence?.chart_manifest?.charts ?? []) {
    const card = document.createElement('article');
    const title = document.createElement('h3'); title.textContent = chart.name;
    const takeaway = document.createElement('p'); takeaway.textContent = chart.takeaway;
    const source = document.createElement('p'); source.textContent = `Source: ${chart.source}`;
    const query = document.createElement('pre'); query.textContent = chart.query;
    const image = document.createElement('img');
    // Uploaded evidence never controls URLs or HTML. Only known local chart names can load.
    if (/^[a-z_]+$/.test(chart.name)) image.src = `/charts/${chart.name}.png`;
    image.alt = chart.name;
    image.onerror = () => { image.hidden = true; };
    card.append(title, image, takeaway, source, query); $('charts').append(card);
  }
}
$('generate').onclick = () => run(async () => loadResult(await api('/api/generate', {})));
$('load').onchange = () => run(async () => {
  const file = $('load').files[0];
  if (file.size > 512000) throw new Error('Result exceeds 512000 bytes');
  const action_data = await file.text();
  loadResult({action_data});
});
$('download').onclick = () => run(async () => {
  if (!payload) throw new Error('Generate or load a result first');
  const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([payload], {type:'application/json'}));
  link.download = 'thesis-result.json'; link.click(); URL.revokeObjectURL(link.href);
});
$('seal').onclick = () => run(async () => {
  if (!payload) throw new Error('Generate or load a result first');
  show('transaction', 'Submitting to Testnet. Wait for final execution; avoid resubmitting if a timeout occurs.');
  try {
    const record = await api('/api/seal', {action_data:payload});
    $('entryId').value = record.entry_id;
    show('transaction', `Transaction: ${record.transaction_id}\nEntry: ${record.entry_id}\nContract: ${record.contract}\nSHA-256: ${record.sha256}`);
    show('record', record.entry);
    show('verification', record.verified_intact ? 'VERIFIED: contract checksums match AND recorded content exactly matches submitted result.' : 'Verification failed');
  } catch(error) { show('transaction', error.message); throw error; }
});
$('verify').onclick = () => run(async () => {
  const entry_id = Number($('entryId').value);
  if (!Number.isSafeInteger(entry_id) || entry_id < 1) throw new Error('Enter a positive integer entry ID');
  const data = await api('/api/verify', {entry_id, action_data:$('candidate').value});
  show('record', data.entry);
  show('verification', data.entry === null ? 'NOT FOUND: no entry exists for this ID.' : data.verified_intact ?
    'VERIFIED: contract checksums match AND recorded content exactly matches candidate.' :
    `MISMATCH: contract verification = ${data.contract_verification}; exact content match = ${data.exact_match}.`);
});
$('ledger').onclick = () => run(async () => {
  const from = Number($('from').value);
  if (!Number.isSafeInteger(from) || from < 1) throw new Error('Enter a positive ledger cursor');
  const data = await api(`/api/entries?from=${from}&limit=10`);
  show('entries', data);
  if (data.page.next_from !== null) $('from').value = data.page.next_from;
});
run(async () => {
  const config = await api('/api/config');
  show('network', `${config.network} · ${config.contract}`);
  show('signing', config.signing_configured ? `Local signer: ${config.signer}. Submission spends Testnet gas.` :
    'Signing is not configured. Generate, load, inspect, download and public verification remain available. Set NEAR_SIGNER_ACCOUNT and NEAR_CREDENTIALS_FILE locally before submitting.');
  loadResult(await api('/api/result'));
  const history = await api('/api/history');
  if (history.entries.length) {
    const last = history.entries.at(-1);
    $('entryId').value = last.entry_id;
    show('transaction', `Previous transaction: ${last.transaction_id}\nEntry: ${last.entry_id}\nNetwork: ${last.network}\nContract: ${last.contract}\nUse Retrieve + verify to check current state.`);
  }
});
