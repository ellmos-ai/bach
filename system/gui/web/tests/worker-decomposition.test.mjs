import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const page = readFileSync(new URL('../src/pages/agenten/running.astro', import.meta.url), 'utf8');
const start = page.indexOf('async function runWorkerAction(');
const end = page.indexOf('async function deleteWorker(', start);
const source = page.slice(start, end).trim();

function actionHarness(state, ok = true) {
  const summary = {textContent: ''};
  const calls = [];
  let refreshes = 0;
  const run = vm.runInNewContext(`(${source})`, {
    document: {getElementById: () => summary},
    fetch: async (url, options) => {
      calls.push({url, body: JSON.parse(options.body)});
      return {ok, json: async () => ({ok, receipt: {state}, detail: ok ? undefined : 'Auftrag geändert'})};
    },
    loadBackgroundWorkers: async () => {refreshes++;},
  });
  return {run, summary, calls, refreshes: () => refreshes};
}

test('decomposition sends the visible generation and exact task content version', async () => {
  const h = actionHarness('pending');
  await h.run('worker-1', 'decompose', 'a'.repeat(32), {task_id: 42, task_version: 'b'.repeat(64)});
  assert.deepEqual(h.calls, [{url: '/api/system/workers/worker-1/decompose',
    body: {generation: 'a'.repeat(32), task_id: 42, task_version: 'b'.repeat(64)}}]);
  assert.match(h.summary.textContent, /angefordert/);
  assert.doesNotMatch(h.summary.textContent, /durch den Lead bestätigt/);
  assert.equal(h.refreshes(), 1);
});

test('only an actual confirmed receipt displays a successful decomposition', async () => {
  const h = actionHarness('confirmed');
  await h.run('worker-1', 'decompose', 'a'.repeat(32), {task_id: 42, task_version: 'b'.repeat(64)});
  assert.equal(h.summary.textContent, 'Teilaufgabenanlage durch den Lead bestätigt.');
});

for (const [state, message] of [['error', 'ohne bestätigte Teilaufgaben'], ['cancelled', 'abgebrochen']]) {
  test(`terminal ${state} receipt is visible without success text`, async () => {
    const h = actionHarness(state);
    await h.run('worker-1', 'decompose', 'a'.repeat(32), {task_id: 42, task_version: 'b'.repeat(64)});
    assert.match(h.summary.textContent, new RegExp(message));
    assert.doesNotMatch(h.summary.textContent, /durch den Lead bestätigt/);
  });
}

test('a stale request error refreshes status without retrying the mutation', async () => {
  const h = actionHarness(undefined, false);
  await h.run('worker-1', 'decompose', 'a'.repeat(32), {task_id: 42, task_version: 'b'.repeat(64)});
  assert.equal(h.calls.length, 1);
  assert.equal(h.summary.textContent, 'Auftrag geändert');
  assert.equal(h.refreshes(), 1);
});

test('unsupported actions never start a provider', async () => {
  const h = actionHarness('pending');
  await h.run('worker-1', 'delegate', 'a'.repeat(32));
  assert.equal(h.calls.length, 0);
});
