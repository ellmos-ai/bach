// Berechnet für einen Task die nächste sinnvolle Handlung samt Begründung.
// Grundlage sind ausschließlich native Felder aus GET /api/tasks bzw.
// GET /api/tasks/<id>: status, require_user_review, github_pr_review_required,
// is_blocked_by_dep, depends_on, claimed_by, claim_expires_at,
// delegation_status. Es werden keine Zusatz-Endpoints benötigt und kein
// preview_worker_selection verwendet.

const DONE_STATUSES = ['done', 'completed', 'closed'];
const CANCELLED_STATUSES = ['cancelled', 'canceled', 'duplicate'];
const TERMINAL_STATUSES = [...DONE_STATUSES, ...CANCELLED_STATUSES];
const ERROR_STATUSES = ['error', 'failed'];
const NATIVE_FIELDS = [
  'require_user_review',
  'github_pr_review_required',
  'is_blocked_by_dep',
  'claimed_by',
  'claim_expires_at',
  'delegation_status'
];

function normalizeStatus(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function parseDependsOn(dependsOn) {
  if (Array.isArray(dependsOn)) {
    return dependsOn.map(item => Number(item)).filter(id => Number.isSafeInteger(id));
  }
  if (typeof dependsOn === 'string' && dependsOn.trim() !== '') {
    return dependsOn
      .split(',')
      .map(part => Number(part.trim()))
      .filter(id => Number.isSafeInteger(id));
  }
  return [];
}

function blockedByDependency(depIds, tasksById) {
  if (!(tasksById instanceof Map)) return { kind: 'unknown' };
  for (const depId of depIds) {
    const dep = tasksById.get(depId);
    if (!dep || typeof dep !== 'object') return { kind: 'missing', id: depId };
    if (!TERMINAL_STATUSES.includes(normalizeStatus(dep.status))) {
      return { kind: 'open', id: depId, status: dep.status };
    }
  }
  return { kind: 'clear' };
}

function appendMissingFieldHints(reason, task, unavailable) {
  let result = reason;
  for (const name of NATIVE_FIELDS) {
    if (task[name] === undefined) {
      unavailable.push(name);
      result += ` Hinweis: Backend liefert ${name} nicht.`;
    }
  }
  return result;
}

export function taskRationale(task, tasksById = null) {
  if (!task || typeof task !== 'object' || Array.isArray(task)) {
    return {
      action: 'Erklärung nicht verfügbar.',
      reason: 'Task-Daten fehlen.',
      reasonKind: 'unavailable',
      unavailable: []
    };
  }

  const status = normalizeStatus(task.status);
  const unavailable = [];
  let action = null;
  let reason = null;
  let reasonKind = null;

  if (DONE_STATUSES.includes(status)) {
    action = 'Abgeschlossen';
    reason = `Der Task gilt als abgeschlossen (Status: ${status}). Keine weitere Handlung nötig.`;
    reasonKind = 'done';
  } else if (CANCELLED_STATUSES.includes(status)) {
    action = 'Keine Handlung nötig';
    reason = `Der Task wurde beendet, ohne abgeschlossen zu werden (Status: ${status}).`;
    reasonKind = 'cancelled';
  } else if (task.require_user_review === true) {
    action = 'Auf Nutzerfreigabe warten';
    reason = 'Der Task erwartet Deine Freigabe (require_user_review=true), bevor es weitergeht.';
    reasonKind = 'review';
  } else if (task.github_pr_review_required === true) {
    action = 'Externen PR-Review abwarten';
    reason = 'Der Task wartet auf den externen Pull-Request-Review (github_pr_review_required=true).';
    reasonKind = 'pr-review';
  } else if (task.is_blocked_by_dep === true) {
    action = 'Warten auf Vorgänger';
    reason = 'Der Task ist von einer noch nicht erledigten Abhängigkeit blockiert (is_blocked_by_dep=true).';
    reasonKind = 'blocked';
  } else if (task.is_blocked_by_dep !== false) {
    const depIds = parseDependsOn(task.depends_on);
    if (depIds.length > 0) {
      const blocked = blockedByDependency(depIds, tasksById);
      if (blocked.kind === 'open') {
        action = 'Warten auf Vorgänger';
        reason = `Die Abhängigkeit Task #${blocked.id} ist noch nicht erledigt (Status: ${blocked.status ?? 'unbekannt'}).`;
        reasonKind = 'blocked';
      } else if (blocked.kind === 'missing') {
        action = 'Abhängigkeitsstatus der Liste nicht eindeutig';
        reason = `Die Abhängigkeit Task #${blocked.id} fehlt in der geladenen Taskliste, daher ist der Blockadestatus unklar.`;
        reasonKind = 'unclear';
      } else if (blocked.kind === 'unknown') {
        action = 'Abhängigkeitsstatus nicht eindeutig';
        reason = 'Der Task hat Abhängigkeiten, deren Erledigungsstatus hier nicht geprüft werden kann.';
        reasonKind = 'unclear';
      }
    }
  }

  if (action === null && typeof task.claimed_by === 'string' && task.claimed_by.trim() !== '') {
    action = 'Warten auf Claim-Ablauf';
    reasonKind = 'claimed';
    if (task.claimed_by === 'user') {
      reason = 'Von Dir beansprucht (claimed_by=user).';
    } else {
      reason = `Fremde Beanspruchung (Lease) von ${task.claimed_by}.`;
    }
    if (task.claim_expires_at != null && String(task.claim_expires_at).trim() !== '') {
      reason += ` Claim läuft ab: ${task.claim_expires_at}.`;
    }
  }

  if (action === null) {
    const delegationStatus = normalizeStatus(task.delegation_status);
    const statusFailed = ERROR_STATUSES.includes(status);
    const delegationFailed = ERROR_STATUSES.includes(delegationStatus);
    if (statusFailed || delegationFailed) {
      action = 'Fehler prüfen';
      const parts = [];
      if (statusFailed) parts.push(`Status: ${status}`);
      if (delegationFailed) parts.push(`Delegationsstatus: ${String(task.delegation_status)}`);
      reason = `Der Task befindet sich in einem Fehlerzustand (${parts.join('; ')}). Fehlerursache prüfen.`;
      reasonKind = 'error';
    }
  }

  if (action === null) {
    action = 'Zur Bearbeitung bereit';
    reason = `Der Task ist offen (Status: ${task.status ?? 'unbekannt'}) und wartet auf Bearbeitung.`;
    reasonKind = 'ready';
  }

  reason = appendMissingFieldHints(reason, task, unavailable);

  return { action, reason, reasonKind, unavailable };
}