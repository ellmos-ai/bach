import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// Liest die GUI-Seite und prüft die Abschlussregel-/Task-Override-Anzeige.
// Die Funktionen werden ohne ausgewählten Task-State in eine frische VM-Sandbox geladen.
const page = readFileSync(new URL('../src/pages/tasks.astro', import.meta.url), 'utf8');

// Konstanten aus dem Quelltext extrahieren (kein "let selectedTask" in diesem Abschnitt).
const constStart = page.indexOf('const COMPLETION_SCOPE');
const constEnd = page.indexOf(';', page.indexOf('const OVERRIDABLE_FIELDS')) + 1;
assert.ok(constStart >= 0 && constEnd > constStart, 'Konstanten-Abschnitt (COMPLETION_SCOPE .. OVERRIDABLE_FIELDS) nicht gefunden');
const consts = vm.runInNewContext(
  page.slice(constStart, constEnd) +
    '\n;({ COMPLETION_SCOPE, GUI_CONSUMER, COMPLETION_RULE_FIELDS, OVERRIDABLE_FIELDS });',
  {}
);

// Funktionsblock: genau die neuen Funktionen, endet vor escapeHtml (dessen Mock in der Sandbox bereitsteht).
const fnSlice = page.slice(page.indexOf('function updateReviewBadge'), page.indexOf('function escapeHtml'));
assert.ok(fnSlice.startsWith('function updateReviewBadge'), 'Funktionsblock ab "function updateReviewBadge" nicht gefunden');

function jsonResponse(ok, status, data) {
  return { ok, status, json: async () => data };
}

function createSandbox(options = {}) {
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, { hidden: false, textContent: '', innerHTML: '' });
    return elements.get(id);
  };
  const calls = { fetch: [], alert: [], detailError: [], openTask: [], loadTasks: [] };
  const sandbox = {
    document: { getElementById: el },
    fetch: async (...args) => {
      calls.fetch.push(args);
      if (options.fetchError) throw new Error(options.fetchError);
      return options.fetchResult;
    },
    alert: (message) => calls.alert.push(message),
    detailError: (message) => calls.detailError.push(message),
    openTask: async (id) => {
      calls.openTask.push(id);
      return options.openTaskResult ?? null;
    },
    loadTasks: () => calls.loadTasks.push(true),
    escapeHtml: (value) => value == null ? '' : String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;'),
    selectedTask: options.selectedTask ?? null,
    COMPLETION_SCOPE: consts.COMPLETION_SCOPE,
    GUI_CONSUMER: consts.GUI_CONSUMER,
    COMPLETION_RULE_FIELDS: consts.COMPLETION_RULE_FIELDS,
    OVERRIDABLE_FIELDS: consts.OVERRIDABLE_FIELDS,
    URLSearchParams: globalThis.URLSearchParams
  };
  vm.runInNewContext(fnSlice, sandbox);
  return { sandbox, calls, el };
}

test('tasks.astro enthält Abschlussregel- und Task-Override-Container', () => {
  for (const marker of [
    'completion-rule-grid',
    'task-override-grid',
    'user-review-badge',
    'completion-pending-note',
    'completion-rule-error',
    'completion-rule-title',
    'completion-rule-version',
    'completion-rule-provider',
    'completion-rule-state'
  ]) {
    assert.ok(page.includes(marker), `Quelltext fehlt Marker: ${marker}`);
  }
  assert.ok(page.includes("const COMPLETION_SCOPE = 'tasks.completion'"));
  assert.ok(page.includes("const GUI_CONSUMER = 'ellmos-system-gui'"));
});

test('Konstanten sind wie erwartet definiert', () => {
  assert.equal(consts.COMPLETION_SCOPE, 'tasks.completion');
  assert.equal(consts.GUI_CONSUMER, 'ellmos-system-gui');
  assert.deepEqual(consts.COMPLETION_RULE_FIELDS, [
    'require_user_review',
    'github_pr_review_required',
    'completion_contract',
    'github_review_contract',
    'result_max_chars'
  ]);
  assert.deepEqual(consts.OVERRIDABLE_FIELDS, [
    'completion_contract',
    'github_review_contract',
    'result_max_chars'
  ]);
});

test('Funktionsblock enthält die neuen Funktionen ohne eigene selectedTask-Bindung', () => {
  for (const fn of [
    'function updateReviewBadge',
    'function completionPendingNote',
    'function loadCompletionRule',
    'function renderTaskOverride',
    'function resetOverride',
    'function completeTask'
  ]) {
    assert.ok(fnSlice.includes(fn), `Funktionsblock fehlt: ${fn}`);
  }
  assert.ok(!/\b(?:let|const|var)\s+selectedTask\b/.test(fnSlice),
    'selectedTask darf im Funktionsblock nicht neu gebunden werden');
});

test('updateReviewBadge zeigt das Badge nur bei require_user_review === true', () => {
  const { sandbox, el } = createSandbox();
  sandbox.updateReviewBadge({ require_user_review: true });
  assert.equal(el('user-review-badge').hidden, false);
  sandbox.updateReviewBadge({ require_user_review: false });
  assert.equal(el('user-review-badge').hidden, true);
  sandbox.updateReviewBadge(null);
  assert.equal(el('user-review-badge').hidden, true);
});

test('renderTaskOverride kennzeichnet Overrides, Reset-Buttons und globale Standards', () => {
  const { sandbox, el } = createSandbox();
  sandbox.renderTaskOverride({
    require_user_review: true,
    completion_contract: { x: 1 },
    result_max_chars: 200,
    github_pr_review_required: false
  });
  const html = el('task-override-grid').innerHTML;
  assert.equal((html.match(/Override aktiv/g) || []).length, 3);
  assert.equal((html.match(/globaler Standard/g) || []).length, 2);
  assert.equal((html.match(/nicht zurücknehmbar/g) || []).length, 1);
  assert.ok(html.includes("resetOverride('completion_contract')"));
  assert.ok(html.includes("resetOverride('result_max_chars')"));
  assert.ok(!html.includes("resetOverride('require_user_review')"));
  assert.ok(html.includes('{&quot;x&quot;:1}'), 'Completion-Contract muss als JSON erscheinen');
  assert.ok(html.includes('>200 <span'), 'Ergebnislimit 200 muss gerendert werden');
  assert.ok(html.includes('id="task-override-result_max_chars"'));
});

test('resetOverride ohne ausgewählten Task ruft die API nicht auf', async () => {
  const { sandbox, calls } = createSandbox({ selectedTask: null });
  await sandbox.resetOverride('result_max_chars');
  assert.equal(calls.fetch.length, 0);
});

test('resetOverride setzt den Override per PUT zurück und lädt den Task neu', async () => {
  const { sandbox, calls } = createSandbox({
    selectedTask: { id: 5 },
    fetchResult: jsonResponse(true, 200, { status: 'updated' })
  });
  await sandbox.resetOverride('result_max_chars');
  assert.equal(calls.fetch.length, 1);
  assert.equal(calls.fetch[0][0], '/api/tasks/5');
  assert.equal(calls.fetch[0][1].method, 'PUT');
  assert.deepEqual(JSON.parse(calls.fetch[0][1].body), { result_max_chars: null, changed_by: 'gui' });
  assert.deepEqual(calls.openTask, [5]);
  assert.equal(calls.detailError.length, 0);
});

test('resetOverride meldet API-Fehler über detailError', async () => {
  const { sandbox, calls } = createSandbox({
    selectedTask: { id: 5 },
    fetchResult: jsonResponse(false, 400, { detail: 'Ungültiges Feld' })
  });
  await sandbox.resetOverride('result_max_chars');
  assert.deepEqual(calls.detailError, ['Ungültiges Feld']);
  assert.equal(calls.openTask.length, 0);
});

test('loadCompletionRule fragt die effektive Policy ab und füllt die Felder', async () => {
  const { sandbox, calls, el } = createSandbox({
    fetchResult: jsonResponse(true, 200, {
      title: 'Regel',
      version: 2,
      provider: { id: 'p', version: '1', source_commit: 'abc' },
      state: 'active'
    })
  });
  await sandbox.loadCompletionRule();
  assert.equal(calls.fetch[0][0],
    '/api/governance/effective-policy?scope=tasks.completion&consumer=ellmos-system-gui');
  assert.equal(el('completion-rule-title').textContent, 'Regel');
  assert.equal(el('completion-rule-version').textContent, '2');
  assert.equal(el('completion-rule-provider').textContent, 'p · 1 · abc');
  assert.equal(el('completion-rule-state').textContent, 'active');
  assert.equal(el('completion-rule-error').hidden, true);
});

test('loadCompletionRule zeigt bei 503 den Grund der Nichtverfügbarkeit', async () => {
  const { sandbox, el } = createSandbox({
    fetchResult: jsonResponse(false, 503, { public_unavailable_reason: 'Registry weg' })
  });
  await sandbox.loadCompletionRule();
  const errEl = el('completion-rule-error');
  assert.ok(errEl.textContent.includes('nicht verfügbar'));
  assert.ok(errEl.textContent.includes('Registry weg'));
  assert.equal(errEl.hidden, false);
});

test('loadCompletionRule weist bei 409 auf geänderten Policy-Snapshot hin', async () => {
  const { sandbox, el } = createSandbox({
    fetchResult: jsonResponse(false, 409, { detail: 'Snapshot' })
  });
  await sandbox.loadCompletionRule();
  const errEl = el('completion-rule-error');
  assert.ok(errEl.textContent.includes('Policy-Snapshot hat sich geändert'));
  assert.ok(errEl.textContent.includes('Snapshot'));
  assert.equal(errEl.hidden, false);
});

test('completeTask meldet Abschluss und zeigt ausstehenden Nutzerreview an', async () => {
  const { sandbox, calls, el } = createSandbox({
    fetchResult: jsonResponse(true, 200, { status: 'updated' }),
    openTaskResult: { id: 5, require_user_review: true }
  });
  await sandbox.completeTask(5);
  assert.equal(calls.fetch[0][0], '/api/tasks/5');
  assert.equal(calls.fetch[0][1].method, 'PUT');
  assert.deepEqual(JSON.parse(calls.fetch[0][1].body), { status: 'completed', changed_by: 'gui' });
  assert.deepEqual(calls.openTask, [5]);
  const note = el('completion-pending-note');
  assert.equal(note.textContent, 'Abschluss gemeldet – Nutzerreview ausstehend');
  assert.equal(note.hidden, false);
  assert.equal(calls.loadTasks.length, 1);
  assert.deepEqual(calls.alert, []);
});

test('completeTask ohne Nutzerreview blendet den Hinweis aus', async () => {
  const { sandbox, el } = createSandbox({
    fetchResult: jsonResponse(true, 200, { status: 'updated' }),
    openTaskResult: { id: 7, require_user_review: false }
  });
  await sandbox.completeTask(7);
  const note = el('completion-pending-note');
  assert.equal(note.textContent, '');
  assert.equal(note.hidden, true);
});

test('completeTask leitet 409-Konflikte an detailError weiter, ohne alert', async () => {
  const { sandbox, calls } = createSandbox({
    fetchResult: jsonResponse(false, 409, { detail: 'Snapshot-Mismatch' })
  });
  await sandbox.completeTask(5);
  assert.deepEqual(calls.detailError, ['Snapshot-Mismatch']);
  assert.deepEqual(calls.alert, []);
  assert.deepEqual(calls.openTask, [5]);
});

test('completeTask zeigt sonstige API-Fehler als alert', async () => {
  const { sandbox, calls } = createSandbox({
    fetchResult: jsonResponse(false, 500, { detail: 'Server kaputt' })
  });
  await sandbox.completeTask(5);
  assert.deepEqual(calls.alert, ['Server kaputt']);
  assert.equal(calls.detailError.length, 0);
});

test('completeTask meldet Netzwerkfehler über alert', async () => {
  const { sandbox, calls } = createSandbox({ fetchError: 'verbindung getrennt' });
  await sandbox.completeTask(5);
  assert.deepEqual(calls.alert, ['Netzwerkfehler: verbindung getrennt']);
});