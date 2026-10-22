// Native backend data mapped to five separate hindrance groups for one task.
// Fail-closed by design: every missing backend answer is reported as
// "unavailable" instead of being interpreted as approval.
// This module performs no client-side pickup or admission simulation.

export const HINDRANCE_GROUPS = [
  { id: "lease", label: "Fremde Lease" },
  { id: "status", label: "Status / Abhängigkeit" },
  { id: "policy", label: "Ausführungsrechte" },
  { id: "binding", label: "Harte Modell-/Zuständigkeitsregeln" },
  { id: "versions", label: "Unveränderte Rückgabe" }
];

export function escapeHtml(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Render any backend value as a stable raw string:
// null, undefined, booleans, JSON for objects, String() otherwise.
function formatValue(value) {
  if (value === null) {
    return "null";
  }
  if (value === undefined) {
    return "undefined";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return "[nicht darstellbar]";
    }
  }
  return String(value);
}

function pushField(entries, kind, name, value) {
  entries.push({ kind, text: `${name}: ${formatValue(value)}` });
}

function markUnavailable(text) {
  return { kind: "unavailable", text };
}

// Fields of the worker-policy "effective" object shown as raw data.
const POLICY_EFFECTIVE_FIELDS = [
  "user_review_required",
  "github_external_review",
  "allow_review_task_pickup",
  "effective_mode",
  "policy_source"
];

// Hard model/binding fields shown as raw data, never interpreted.
const BINDING_FIELDS = ["required_model", "assigned_slot", "assigned_to"];

function buildLeaseEntries(task, lease) {
  const entries = [];
  if (!isPlainObject(lease)) {
    entries.push(markUnavailable("Lease-Daten nicht abrufbar (fail-closed: keine Aussage über fremde Lease möglich)"));
  } else if (lease.leased === true && lease.own !== true) {
    entries.push({ kind: "hindrance", text: "Fremde Lease aktiv (leased: true, own: nicht dieses Gerät)" });
    if (isPlainObject(lease.holder)) {
      pushField(entries, "hindrance", "holder.worker_id", lease.holder.worker_id);
      pushField(entries, "hindrance", "holder.host", lease.holder.host);
      pushField(entries, "hindrance", "holder.intent", lease.holder.intent);
      pushField(entries, "hindrance", "holder.expires_at", lease.holder.expires_at);
    } else {
      entries.push(markUnavailable("Lease-Inhaber (holder) nicht abrufbar"));
    }
  } else if (lease.legacy === true) {
    entries.push({ kind: "info", text: "Lease ist ein Legacy-Eintrag (legacy: true)" });
  } else if (lease.own === true) {
    entries.push({ kind: "info", text: "Lease dieses Geräts (own: true) – keine fremde Lease" });
  } else if (lease.leased === false) {
    entries.push({ kind: "info", text: "Keine aktive Lease (leased: false)" });
  } else {
    entries.push(markUnavailable("Lease-Zustand nicht eindeutig abrufbar (fail-closed)"));
  }
  if (isPlainObject(task) && "claimed_by" in task) {
    entries.push({
      kind: "info",
      text: `claimed_by: ${formatValue(task.claimed_by)} (historisch, keine Aussage über die aktuelle Lease)`
    });
  }
  return entries;
}

function buildStatusEntries(task) {
  const entries = [];
  if (!isPlainObject(task)) {
    entries.push(markUnavailable("Aufgabendetails nicht abrufbar (fail-closed)"));
    return entries;
  }
  if ("status" in task) {
    pushField(entries, "info", "status", task.status);
  } else {
    entries.push(markUnavailable("status nicht abrufbar"));
  }
  if ("is_blocked_by_dep" in task) {
    if (task.is_blocked_by_dep === true) {
      entries.push({ kind: "hindrance", text: "is_blocked_by_dep: true – Aufgabe ist durch ihre Abhängigkeit blockiert" });
    } else {
      pushField(entries, "info", "is_blocked_by_dep", task.is_blocked_by_dep);
    }
  } else {
    entries.push(markUnavailable("is_blocked_by_dep nicht abrufbar (fail-closed)"));
  }
  if ("depends_on" in task) {
    pushField(entries, "info", "depends_on", task.depends_on);
  } else {
    entries.push(markUnavailable("depends_on nicht abrufbar (fail-closed)"));
  }
  return entries;
}

function buildPolicyEntries(policy, policyError) {
  const entries = [];
  if (policyError) {
    const statusSuffix = "status" in policyError ? ` (HTTP ${formatValue(policyError.status)})` : "";
    entries.push(markUnavailable(`Worker-Policy nicht abrufbar${statusSuffix} – fail-closed, keine Aussage über Ausführungsrechte`));
    return entries;
  }
  if (!isPlainObject(policy) || !isPlainObject(policy.effective)) {
    entries.push(markUnavailable("Worker-Policy-Daten nicht abrufbar (fail-closed)"));
    return entries;
  }
  for (const field of POLICY_EFFECTIVE_FIELDS) {
    if (field in policy.effective) {
      pushField(entries, "info", `effective.${field}`, policy.effective[field]);
    } else {
      entries.push(markUnavailable(`effective.${field} nicht abrufbar (fail-closed)`));
    }
  }
  return entries;
}

function buildBindingEntries(task) {
  const entries = [];
  if (!isPlainObject(task)) {
    entries.push(markUnavailable("Aufgabendetails nicht abrufbar (fail-closed)"));
    return entries;
  }
  for (const field of BINDING_FIELDS) {
    if (field in task) {
      pushField(entries, "info", field, task[field]);
    } else {
      entries.push(markUnavailable(`${field} nicht abrufbar (fail-closed)`));
    }
  }
  return entries;
}

function buildVersionEntries(task, lease) {
  const entries = [];
  if (isPlainObject(task) && "task_version" in task) {
    entries.push({ kind: "info", text: `task_version (Detail-GET): ${formatValue(task.task_version)}` });
  } else {
    entries.push(markUnavailable("task_version (Detail-GET) nicht abrufbar (fail-closed)"));
  }
  if (isPlainObject(lease) && "task_version" in lease) {
    entries.push({ kind: "info", text: `task_version (Lease-GET): ${formatValue(lease.task_version)}` });
  } else {
    entries.push(markUnavailable("task_version (Lease-GET) nicht abrufbar (fail-closed)"));
  }
  if (isPlainObject(lease) && "fence" in lease) {
    entries.push({ kind: "info", text: `fence (Lease-GET): ${formatValue(lease.fence)}` });
  } else {
    entries.push(markUnavailable("fence (Lease-GET) nicht abrufbar (fail-closed)"));
  }
  return entries;
}

export function buildTaskHindrances(input = {}) {
  const data = isPlainObject(input) ? input : {};
  const task = isPlainObject(data.task) ? data.task : null;
  const lease = isPlainObject(data.lease) ? data.lease : null;
  const policy = isPlainObject(data.policy) ? data.policy : null;
  const policyError = data.policyError ? data.policyError : null;

  const builders = {
    lease: () => buildLeaseEntries(task, lease),
    status: () => buildStatusEntries(task),
    policy: () => buildPolicyEntries(policy, policyError),
    binding: () => buildBindingEntries(task),
    versions: () => buildVersionEntries(task, lease)
  };

  const groups = HINDRANCE_GROUPS.map((group) => {
    const entries = builders[group.id]();
    let state = "info";
    if (entries.some((entry) => entry.kind === "hindrance")) {
      state = "hindrance";
    } else if (entries.some((entry) => entry.kind === "unavailable")) {
      state = "unavailable";
    }
    return { id: group.id, label: group.label, state, entries };
  });

  const hasHindrances = groups.some((group) => group.state === "hindrance");

  return { groups, hasHindrances };
}

export function renderTaskHindrances(data) {
  const model = data && Array.isArray(data.groups) ? data : buildTaskHindrances(data);
  const blockedCount = model.groups.filter((group) => group.state === "hindrance").length;
  const unavailableCount = model.groups.filter((group) => group.state === "unavailable").length;

  const parts = [];
  parts.push('<div class="task-hindrances">');
  parts.push('<p class="task-hindrances-summary">');
  parts.push(escapeHtml(`Belegte Übernahmehindernisse in ${blockedCount} von ${model.groups.length} Gruppen.`));
  if (unavailableCount > 0) {
    parts.push(escapeHtml(` ${unavailableCount} Gruppen mit nicht abrufbaren Daten (fail-closed, keine Aussage).`));
  }
  parts.push("</p>");
  parts.push('<p class="task-hindrances-note">Rohdaten aus Lease-, Policy- und Aufgaben-Endpunkten; fehlende Daten gelten als nicht abrufbar. Keine clientseitige Zulassungssimulation.</p>');
  for (const group of model.groups) {
    parts.push(`<section class="task-hindrance-group task-hindrance-group--${escapeHtml(group.state)}" data-group="${escapeHtml(group.id)}">`);
    parts.push(`<h4 class="task-hindrance-group-label">${escapeHtml(group.label)}</h4>`);
    parts.push('<ul class="task-hindrance-entries">');
    for (const entry of group.entries) {
      parts.push(`<li class="task-hindrance-entry task-hindrance-entry--${escapeHtml(entry.kind)}">${escapeHtml(entry.text)}</li>`);
    }
    parts.push("</ul>");
    parts.push("</section>");
  }
  parts.push("</div>");
  return parts.join("");
}