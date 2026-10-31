import test from 'node:test';
import assert from 'node:assert/strict';
import { taskRationale } from '../src/lib/task-rationale.mjs';

test('done-Task gilt als abgeschlossen', () => {
  const result = taskRationale({ id: 1, status: 'done' });
  assert.equal(result.action, 'Abgeschlossen');
  assert.equal(result.reasonKind, 'done');
});

test('cancelled-Task braucht keine Handlung', () => {
  const result = taskRationale({ id: 2, status: 'cancelled' });
  assert.equal(result.action, 'Keine Handlung nötig');
  assert.equal(result.reasonKind, 'cancelled');
});

test('require_user_review wartet auf Nutzerfreigabe', () => {
  const result = taskRationale({ id: 3, status: 'pending', require_user_review: true });
  assert.equal(result.action, 'Auf Nutzerfreigabe warten');
  assert.equal(result.reasonKind, 'review');
});

test('github_pr_review_required wartet auf externen Review', () => {
  const result = taskRationale({ id: 4, status: 'pending', github_pr_review_required: true });
  assert.equal(result.action, 'Externen PR-Review abwarten');
  assert.equal(result.reasonKind, 'pr-review');
});

test('is_blocked_by_dep blockiert auf Vorgänger', () => {
  const result = taskRationale({ id: 5, status: 'pending', is_blocked_by_dep: true, depends_on: '9' });
  assert.equal(result.action, 'Warten auf Vorgänger');
  assert.equal(result.reasonKind, 'blocked');
});

test('offene Abhängigkeit in der Liste blockiert', () => {
  const tasksById = new Map([[9, { id: 9, status: 'pending' }]]);
  const result = taskRationale({ id: 6, status: 'pending', depends_on: '9' }, tasksById);
  assert.equal(result.action, 'Warten auf Vorgänger');
  assert.equal(result.reasonKind, 'blocked');
});

test('fehlende Abhängigkeit in der Liste ist unklar', () => {
  const tasksById = new Map();
  const result = taskRationale({ id: 7, status: 'pending', depends_on: '9' }, tasksById);
  assert.equal(result.action, 'Abhängigkeitsstatus der Liste nicht eindeutig');
  assert.equal(result.reasonKind, 'unclear');
});

test('Abhängigkeiten ohne Liste sind unklar', () => {
  const result = taskRationale({ id: 8, status: 'pending', depends_on: '9' }, null);
  assert.equal(result.action, 'Abhängigkeitsstatus nicht eindeutig');
  assert.equal(result.reasonKind, 'unclear');
});

test('erledigte Abhängigkeiten blockieren nicht', () => {
  const tasksById = new Map([[9, { id: 9, status: 'done' }]]);
  const result = taskRationale({ id: 9, status: 'pending', depends_on: '9' }, tasksById);
  assert.equal(result.action, 'Zur Bearbeitung bereit');
  assert.equal(result.reasonKind, 'ready');
});

test('fremde Beanspruchung nennt Ablaufzeit', () => {
  const result = taskRationale({
    id: 10,
    status: 'pending',
    claimed_by: 'agent-7',
    claim_expires_at: '2026-10-22T12:00:00Z'
  });
  assert.equal(result.action, 'Warten auf Claim-Ablauf');
  assert.equal(result.reasonKind, 'claimed');
  assert.ok(result.reason.includes('Fremde Beanspruchung (Lease) von agent-7'));
  assert.ok(result.reason.includes('Claim läuft ab: 2026-10-22T12:00:00Z'));
});

test('offener Task ohne Claim ist bereit', () => {
  const result = taskRationale({ id: 11, status: 'pending' });
  assert.equal(result.action, 'Zur Bearbeitung bereit');
  assert.equal(result.reasonKind, 'ready');
  assert.ok(result.reason.includes('wartet auf Bearbeitung'));
  assert.ok(!result.reason.includes('Claim'));
});

test('fehlende native Felder werden als Hinweis gemeldet', () => {
  const result = taskRationale({ id: 12, status: 'pending' });
  assert.ok(result.unavailable.includes('require_user_review'));
  assert.ok(result.reason.includes('Hinweis: Backend liefert require_user_review nicht.'));
});

test('Fehlerstatus verlangt Fehlerprüfung', () => {
  const result = taskRationale({ id: 13, status: 'pending', delegation_status: 'failed' });
  assert.equal(result.action, 'Fehler prüfen');
  assert.equal(result.reasonKind, 'error');
  assert.ok(result.reason.includes('Delegationsstatus: failed'));
});

test('ohne Task-Daten gibt es keine Erklärung', () => {
  const result = taskRationale(null);
  assert.equal(result.action, 'Erklärung nicht verfügbar.');
  assert.equal(result.reasonKind, 'unavailable');
  assert.deepEqual(result.unavailable, []);
});